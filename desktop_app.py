"""One-window portable Windows launcher for the QA modules."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import queue
import socket
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QPlainTextEdit, QFileDialog, QMessageBox, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QCheckBox, QHeaderView, QScrollArea)
from desktop_store import SettingsStore

DEFAULTS = {'card_selector':'.card', 'value_selector':'.card-value',
    'launch_mode':'auto',
    'suit_selector':'.card-suit', 'id_attribute':'data-card-id',
    'mode':'scopa', 'state_selector':'#game-state',
    'hand_selector':'#player-hand .card', 'table_selector':'#table-cards .card',
    'confirm_selector':'#confirm-move', 'selected_attribute':'aria-pressed',
    'goal':'', 'strategy':'vision', 'ai_url':'http://127.0.0.1:11434', 'ai_model':'', 'max_chips':'100',
    'ai_vision':'no',
    'login_mode':'auto', 'open_login_selector':'',
    'username_selector':'input[name="username"], input[type="email"], input[autocomplete="username"]',
    'password_selector':'input[type="password"]',
    'submit_selector':'button[type="submit"], input[type="submit"]',
    'success_selector':''}
LABELS = {'card_selector':'Карточка', 'value_selector':'Значение карточки',
    'launch_mode':'Запуск системы',
    'suit_selector':'Масть', 'id_attribute':'Атрибут ID',
    'mode':'Режим (scopa / cards)', 'state_selector':'JSON полного состояния',
    'hand_selector':'Карты в руке', 'table_selector':'Карты на столе',
    'confirm_selector':'Подтверждение хода', 'selected_attribute':'Атрибут выбора (true)',
    'goal':'Что искать / задача', 'strategy':'Как искать', 'ai_url':'Адрес локального Ollama',
    'ai_model':'Установленная модель Ollama', 'max_chips':'Максимум фишек при вводе числа',
    'ai_vision':'Скриншот для локальной модели',
    'login_mode':'Режим входа', 'open_login_selector':'Кнопка открытия входа (необязательно)',
    'username_selector':'Поле логина', 'password_selector':'Поле пароля',
    'submit_selector':'Кнопка входа', 'success_selector':'Признак успешного входа'}
STATUS = {'pending':'Ожидание', 'starting':'Открываю браузер', 'browser_ready':'Браузер готов',
    'authenticating':'Вход в аккаунт', 'navigating':'Открываю страницу игры',
    'collecting':'Сбор данных', 'analyzing':'Расчёт', 'acting':'Действие',
    'completed':'Работает', 'retrying':'Повтор', 'stale_snapshot':'Обновление страницы',
    'action_outcome_unknown':'Проверь результат клика', 'failed':'Ошибка запуска',
    'error_limit_reached':'Остановлен: ошибки', 'cancelled':'Остановлен',
    'waiting_turn':'Ожидаю ход / новый пример'}
STATUS.update({'waiting_user':'Пауза / ожидает продолжения','checking_room':'Проверяю игровой стол',
               'waiting_room':'Стол не распознан','browser_closed':'Браузер закрыт'})
STATUS.update({'agent_searching':'Агент ищет комнату','agent_playing':'ИИ выполняет действие'})
STATUS['engine_ready']='Кімната готова • математика підключена'
STATUS['authenticated']='Вхід підтверджено • шукаю Scopa'
STATUS['table_locked']='Стіл зафіксовано'
STATUS['waiting_table']='Ожидаю комнату / начало бесплатного стола'
STATUS['table_changed']='Стіл змінився • хід зупинено'

def bundled_engine():
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    external=root/'ScopaEngine.exe'
    if external.is_file(): return str(external)
    embedded=Path(getattr(sys,'_MEIPASS',root))/'engine'/'ScopaEngine.exe'
    if embedded.is_file(): return str(embedded)
    raise ValueError('Не найден ScopaEngine.exe. Пересобери приложение или положи движок рядом.')

class Events(QObject):
    finished = Signal(str)
    message = Signal(str)
    outcome = Signal(str, object)

async def run_system(settings, directory, stop, events, controls=None):
    import uvicorn
    from fastapi.responses import HTMLResponse
    from engine_server import create_app
    from test_orchestrator import TestOrchestrator, origin, proxy_config
    logging.basicConfig(filename=directory/'server_log.txt', encoding='utf-8', level=logging.INFO)
    site = settings['site']
    automatic = (site.get('launch_mode','auto')=='auto' and not site.get('demo',False)) or site.get('workflow_demo',False)
    if site.get('mode')=='agent':
        raise ValueError('Теперь ходы выбирает математический движок. В настройках выбери Scopa или внешний движок карточек.')
    channel = 'shard'
    events.message.emit('Браузер: ShardBrowser • окремий профіль для кожного акаунта')
    sessions = []
    for account in settings['accounts']:
        proxy_config(account.get('proxy'))
        session = {'id':account['id'], 'url':site['url'], 'proxy':account.get('proxy') or None,
                   'browser':'chromium', 'browser_channel':channel,'connection_mode':'cdp',
                   'cdp_headless':site.get('cdp_headless',False)}
        if site.get('demo'):
            session['url']=('http://127.0.0.1:5000/workflow/login?sid=' if site.get('workflow_demo') else 'http://127.0.0.1:5000/demo?sid=')+account['id']
        if site.get('workflow_demo'):
            from workflow_demo import USER,PASSWORD
            session['proxy']=None
            session['auth']={'url':session['url'],'username':USER,'password':PASSWORD,'mode':'auto'}
        elif automatic and account.get('login'):
            session['auth']={'url':site.get('login_url') or site['url'],
                'username':account['login'],'password':account.get('password',''),
                'mode':site.get('login_mode','auto'),'open_selector':site.get('open_login_selector',''),
                **{k:site.get(k,DEFAULTS[k]) for k in ('username_selector','password_selector','submit_selector','success_selector')}}
            if session['auth']['mode']=='auto' and session['auth']['success_selector']=='.card':session['auth']['success_selector']=''
        sessions.append(session)
    visual=(site.get('strategy','vision')=='vision' and not site.get('demo')) or site.get('vision_demo',False)
    if visual:
        for session in sessions:
            if session.get('auth'):
                session['auth']['vision']={'strategy':'ollama','ai_vision':True,'ai_url':site.get('ai_url',DEFAULTS['ai_url']),
                    'ai_model':site.get('ai_model',''),'goal':'','max_chips':int(site.get('max_chips',100))}
    origin(site['url'])
    config = {'sessions':sessions, 'log_file':'bot_log.txt', 'stealth_enabled':False,
        'engine_gate_url':'http://127.0.0.1:5000/room-ready','engine_gate_token':uuid.uuid4().hex,
        'setup_timeout_seconds':180 if visual else 60,'cycle_timeout_seconds':120 if visual else 45,
        'manual_start':not site.get('demo',False) or site.get('workflow_demo',False),
        'manual_login':not automatic,
        'room_agent':{'goal':site.get('goal',''),'strategy':'ollama' if visual else ('text' if site.get('strategy','vision')=='vision' else site.get('strategy','text')),
            'auto_discover':True,'preferred_game':'Scopa' if site.get('mode','scopa')=='scopa' else site.get('game_name','Scopa'),
            'state_json':site.get('mode','scopa')=='scopa',
            'exclude_selector':site.get('hand_selector',DEFAULTS['hand_selector'])+', '+site.get('table_selector',DEFAULTS['table_selector']),
            'ai_url':site.get('ai_url',DEFAULTS['ai_url']),'ai_model':site.get('ai_model',''),
            'ai_vision':visual or site.get('ai_vision','no')=='yes',
            'max_chips':int(site.get('max_chips',100))},
        'interval_seconds':1, 'dom': {'api_url':'http://127.0.0.1:5000/analyze',
            **{k:site.get(k,DEFAULTS[k]) for k in ('card_selector','value_selector','suit_selector','id_attribute',
                'mode','state_selector','hand_selector','table_selector','confirm_selector','selected_attribute')}}}
    # Fail before launching browsers if an unrelated server owns this port.
    sock = socket.socket()
    try:
        sock.bind(('127.0.0.1',5000))
    except OSError as exc:
        raise ValueError('Порт 5000 занят. Закрой ранее запущенный сервер.') from exc
    finally:
        sock.close()
    engine = bundled_engine() if site.get('demo') else settings.get('engine','') or bundled_engine()
    if engine:
        engine_path = Path(engine).resolve()
        if not engine_path.is_file() or engine_path.suffix.lower() != '.exe':
            raise ValueError('Выбери существующий .exe математического движка.')
        engine_config = {'command':[str(engine_path)], 'cwd':str(engine_path.parent),
            'require_room_ready':True,'gate_token':config['engine_gate_token'],'session_ids':[s['id'] for s in sessions]}
        app = create_app(directory/'engine.json', config_data=engine_config)
    from scopa_demo import mount_demo
    assets=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
    mount_demo(app,assets/'scopa_demo.html')
    from workflow_demo import mount_workflow
    mount_workflow(app,assets/'scopa_demo.html')
    server = uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=5000,log_config=None,
                                         access_log=False, ws='none', http='h11', loop='asyncio'))
    orchestrator = TestOrchestrator(directory/'runtime.json', config_data=config)
    own_controls=controls is None
    controls=controls or {a['id']:threading.Event() for a in settings['accounts']}
    if automatic and own_controls:
        for control in controls.values():control.set()
    orchestrator.start_requested=lambda sid:controls[sid].is_set()
    orchestrator.clear_start=lambda sid:controls[sid].clear()
    orchestrator.resume_start=lambda sid:controls[sid].set()
    def outcome(sid,data):
        directory.mkdir(parents=True,exist_ok=True)
        (directory/('last_move_'+sid+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        if hasattr(events,'outcome'): events.outcome.emit(sid,data)
        events.message.emit('Ход подтверждён: '+data['move']['played_card']+' → '+', '.join(data['move']['captured_cards']))
    orchestrator.on_outcome=outcome
    server_task = asyncio.create_task(server.serve())
    worker_task = None
    vision_runtime=None
    try:
        from shard_browser import prepare_runtime
        config['shard_sdk']=await prepare_runtime(directory/'shard_profiles',events.message.emit)
        if stop.is_set():return
        if visual:
            from vision_runtime import VisionRuntime
            vision_runtime=VisionRuntime(events.message.emit)
            model=await vision_runtime.start()
            config['room_agent'].update(ai_url='http://127.0.0.1:11434',ai_model=model)
            for session in sessions:
                if session.get('auth',{}).get('vision'):
                    session['auth']['vision'].update(ai_url='http://127.0.0.1:11434',ai_model=model)
        async with asyncio.timeout(15):
            while not server.started:
                if server_task.done():
                    server_task.result()
                    raise RuntimeError('Не удалось запустить локальный API.')
                await asyncio.sleep(.05)
        events.message.emit('Локальный API запущен. Открываю браузеры…')
        worker_task = asyncio.create_task(orchestrator.run())
        while not stop.is_set() and not worker_task.done() and not server_task.done():
            await asyncio.sleep(.15)
        if worker_task.done():
            worker_task.result()
            events.message.emit('Все сессии завершились. Проверь статусы и настройки сайта.')
    finally:
        if worker_task is not None:
            await orchestrator.stop()
            await asyncio.gather(worker_task,return_exceptions=True)
        server.should_exit = True
        if vision_runtime:await vision_runtime.close()
        try:
            await asyncio.wait_for(server_task,5)
        except TimeoutError:
            server_task.cancel()
            await asyncio.gather(server_task,return_exceptions=True)

class FormDialog(QDialog):
    def __init__(self, title, fields, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(560,200)
        outer=None
        if len(fields)>10:
            self.resize(650,650); outer=QVBoxLayout(self)
            note=QLabel('Автоматический запуск: вход → поиск игры/комнаты → посадка → ходы движка.\nДля обычных форм входа оставь автоматический поиск полей.')
            note.setWordWrap(True); outer.addWidget(note)
            scroll=QScrollArea(); scroll.setWidgetResizable(True); container=QWidget(); scroll.setWidget(container)
            outer.addWidget(scroll); layout=QFormLayout(container)
        else:
            layout=QFormLayout(self)
        self.inputs={}
        for key,label in fields:
            if key=='launch_mode':
                widget=QComboBox();widget.addItem('Автоматически — полный цикл','auto');widget.addItem('Вручную — войти самому и нажать Начать работу','manual')
                widget.setCurrentIndex(max(0,widget.findData(values.get(key,'auto'))))
                self.inputs[key]=widget;layout.addRow(label,widget);continue
            if key=='ai_vision':
                widget=QComboBox();widget.addItem('Нет — только текст и элементы','no');widget.addItem('Да — нужна модель с поддержкой изображений','yes')
                widget.setCurrentIndex(max(0,widget.findData(values.get(key,'no'))))
                self.inputs[key]=widget;layout.addRow(label,widget);continue
            if key in {'mode','strategy'}:
                widget=QComboBox()
                choices=([('Scopa — математический движок','scopa'),('Карточки — внешний движок','cards')]
                    if key=='mode' else [('Поиск по тексту — без ИИ','text'),('ИИ Ollama — нужна установленная модель','ollama'),('По скриншотам — вход и поиск стола','vision')])
                for text,value in choices: widget.addItem(text,value)
                widget.setCurrentIndex(max(0,widget.findData(values.get(key,DEFAULTS[key]))))
                self.inputs[key]=widget;layout.addRow(label,widget);continue
            if key=='login_mode':
                widget=QComboBox(); widget.addItem('Автоматически — найти кнопку и форму','auto'); widget.addItem('Вручную — использовать селекторы','manual')
                widget.setCurrentIndex(max(0,widget.findData(values.get(key,'auto'))))
                self.inputs[key]=widget; layout.addRow(label,widget); continue
            widget=QLineEdit(str(values.get(key,'')))
            if key=='password': widget.setEchoMode(QLineEdit.Password)
            if key=='proxy': widget.setPlaceholderText('http://IP:порт или http://логин:пароль@IP:порт')
            if key in {'open_login_selector','username_selector','password_selector','submit_selector','success_selector'}:
                widget.setPlaceholderText('Можно оставить пустым для автоматического поиска')
            self.inputs[key]=widget; layout.addRow(label,widget)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        if outer is not None: outer.addWidget(buttons)
        else: layout.addRow(buttons)
    def values(self): return {k:(w.currentData() if isinstance(w,QComboBox) else w.text()) for k,w in self.inputs.items()}

class MainWindow(QMainWindow):
    def __init__(self, directory):
        super().__init__()
        self.directory=Path(directory); self.store=SettingsStore(self.directory)
        self.settings=self.store.load(); self.thread=None; self.stop_event=threading.Event()
        self.controls={}
        self.events=Events(); self.events.finished.connect(self.finished); self.events.message.connect(self.append_log)
        self.events.outcome.connect(self.show_outcome)
        self.closing=False; self.log_offset=0; self.account_rows=[]
        self.setWindowTitle('CDP • ІІ та математичний движок'); self.resize(960,680)
        self.setMinimumSize(900,680)
        self.setStyleSheet('''QWidget{font-size:14px} QMainWindow{background:#f5f7fb}
QPushButton{padding:8px 14px} QLineEdit,QComboBox{padding:7px}
QTableWidget,QPlainTextEdit{background:white;border:1px solid #d1d9e6}
QLabel#title{font-size:24px;font-weight:bold}''')
        root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root); layout.setContentsMargins(24,20,24,20)
        title=QLabel('CDP • ІІ та математичний движок'); title.setObjectName('title'); layout.addWidget(title)
        layout.addWidget(QLabel('Браузер → ІІ входить у кімнату → підтвердження столу → математичний движок'))
        self.agent_button=QPushButton('Stagehand • промпты для ИИ')
        self.agent_button.clicked.connect(self.open_prompt_agent)
        layout.addWidget(self.agent_button)
        row=QHBoxLayout(); self.sites=QComboBox(); row.addWidget(self.sites,1)
        self.add_site_button=QPushButton('Додати сайт'); self.add_site_button.clicked.connect(self.add_site); row.addWidget(self.add_site_button)
        self.site_settings_button=QPushButton('Змінити адресу'); self.site_settings_button.clicked.connect(self.site_settings); row.addWidget(self.site_settings_button)
        layout.addLayout(row)
        goal_row=QHBoxLayout();goal_row.addWidget(QLabel('Задача для ІІ:'))
        self.goal=QLineEdit();self.goal.setPlaceholderText('Необов’язково: гра: Scopa; кімната: Учебная; стіл: 5; фішки: 10')
        goal_row.addWidget(self.goal,1);self.save_goal_button=QPushButton('Зберегти');self.save_goal_button.clicked.connect(self.save_goal);goal_row.addWidget(self.save_goal_button)
        layout.addLayout(goal_row)
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(['Акаунт','Проксі','Браузер / ІІ','Мат. движок'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setMinimumHeight(150)
        layout.addWidget(self.table)
        row=QHBoxLayout()
        self.add_account_button=QPushButton('Додати акаунт'); self.add_account_button.clicked.connect(lambda:self.account_dialog())
        self.edit_account_button=QPushButton('Змінити'); self.edit_account_button.clicked.connect(self.edit_account)
        self.remove_account_button=QPushButton('Видалити'); self.remove_account_button.clicked.connect(self.remove_account)
        for button in (self.add_account_button,self.edit_account_button,self.remove_account_button): row.addWidget(button)
        row.addStretch(); layout.addLayout(row)
        row=QHBoxLayout(); self.engine_label=QLabel(); row.addWidget(self.engine_label,1)
        self.engine_button=QPushButton('Обрати мат. движок'); self.engine_button.clicked.connect(self.choose_engine); row.addWidget(self.engine_button)
        self.demo_engine_button=QPushButton('Вбудований Scopa'); self.demo_engine_button.clicked.connect(self.clear_engine); row.addWidget(self.demo_engine_button)
        layout.addLayout(row)
        self.stealth=QCheckBox();self.stealth.setChecked(False);self.stealth.hide()
        row=QHBoxLayout(); self.start_button=QPushButton('Запустити'); self.start_button.setStyleSheet('background:#235be8;color:white;padding:10px 24px')
        self.start_button.clicked.connect(self.start); row.addWidget(self.start_button)
        self.work_button=QPushButton('Продовжити'); self.work_button.clicked.connect(self.begin_work); self.work_button.setEnabled(False); row.addWidget(self.work_button)
        self.pause_button=QPushButton('Пауза'); self.pause_button.clicked.connect(self.pause_work); self.pause_button.setEnabled(False); row.addWidget(self.pause_button)
        self.stop_button=QPushButton('Зупинити'); self.stop_button.clicked.connect(self.stop); self.stop_button.setEnabled(False); row.addWidget(self.stop_button)
        self.demo_button=QPushButton();self.demo_button.hide()
        self.vision_demo_button=QPushButton('Перевірити на демо'); self.vision_demo_button.clicked.connect(lambda checked=False:self.demo(True));row.addWidget(self.vision_demo_button)
        row.addStretch(); layout.addLayout(row)
        self.decision=QLabel('Мат. движок очікує: ІІ має увійти в кімнату, сісти за стіл і отримати повний стан гри.')
        self.decision.setWordWrap(True); self.decision.setStyleSheet('background:#e8efff;padding:14px;border-radius:8px'); layout.addWidget(self.decision)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(800); layout.addWidget(self.log,1)
        self.note=QLabel('Готово. Настройки сохраняются автоматически.'); layout.addWidget(self.note)
        self.sites.currentIndexChanged.connect(self.refresh_accounts)
        self.reload_sites(); self.update_engine_label()
        self.timer=QTimer(self); self.timer.timeout.connect(self.poll_log); self.timer.start(400)

    def open_prompt_agent(self):
        from stagehand_dialog import AgentDialog
        AgentDialog(self.settings,self.save,self).exec()

    def save(self):
        self.settings['stealth']=self.stealth.isChecked(); self.store.save(self.settings)
    def current_site(self):
        sid=self.sites.currentData()
        return next((s for s in self.settings['sites'] if s['id']==sid),None)
    def reload_sites(self, selected=None):
        self.sites.blockSignals(True); self.sites.clear()
        for site in self.settings['sites']: self.sites.addItem(site['name'],site['id'])
        if selected: self.sites.setCurrentIndex(self.sites.findData(selected))
        self.sites.blockSignals(False); self.refresh_accounts()
    def refresh_accounts(self):
        site=self.current_site()
        if hasattr(self,'goal'):self.goal.setText(site.get('goal','') if site else '')
        self.account_rows=[a for a in self.settings['accounts'] if a['site_id']==self.sites.currentData()]
        self.table.setRowCount(len(self.account_rows))
        for row,a in enumerate(self.account_rows):
            proxy=urlparse(a.get('proxy') or '')
            display=f'{proxy.hostname}:{proxy.port}' if proxy.hostname else 'Без прокси'
            for col,value in enumerate((a.get('login') or 'Без входу',display,'Готово','Очікує кімнату')):
                self.table.setItem(row,col,QTableWidgetItem(value))
    def add_site(self):
        dialog=FormDialog('Добавить сайт',[('name','Название'),('url','Адрес сайта')],{},self)
        if dialog.exec()!=QDialog.Accepted: return
        values=dialog.values(); p=urlparse(values['url'].strip())
        if p.scheme not in ('http','https') or not p.hostname:
            QMessageBox.warning(self,'Адрес','Укажи полный адрес: https://example.com'); return
        sid=uuid.uuid4().hex; self.settings['sites'].append({'id':sid,'name':values['name'].strip() or p.hostname,
            'url':values['url'].strip(),'login_url':values['url'].strip(),**DEFAULTS})
        self.save(); self.reload_sites(sid)
        self.append_log('Сайт добавлен. Для нового интерфейса проверь «Настройки сайта».')
    def site_settings(self):
        site=self.current_site()
        if not site: return
        fields=[('name','Назва'),('url','Адреса сайту'),('login_url','Сторінка входу (можна головну)')]
        dialog=FormDialog('Адреса сайту',fields,site,self)
        if dialog.exec()!=QDialog.Accepted: return
        values=dialog.values()
        try:
            for key in ('url','login_url'):
                p=urlparse(values[key]); assert p.scheme in ('http','https') and p.hostname
        except (AssertionError,ValueError):
            QMessageBox.warning(self,'Адреса','Укажи повні адреси http:// або https://.'); return
        site.update(values); self.save(); self.reload_sites(site['id'])
    def save_goal(self):
        site=self.current_site()
        if site:
            site['goal']=self.goal.text().strip();self.save()
            self.append_log('Задача сохранена. При автоматическом запуске агент войдёт и начнёт поиск сам.')
    def account_dialog(self, account=None):
        site=self.current_site()
        if not site:
            QMessageBox.information(self,'Сайт','Сначала добавь сайт.'); return
        dialog=FormDialog('Аккаунт и прокси',[('login','Логин (пусто — без авторизации)'),('password','Пароль'),
            ('proxy','Прокси URL (пусто — без прокси)')],account or {},self)
        if dialog.exec()!=QDialog.Accepted: return
        values=dialog.values(); values['proxy']=values['proxy'].strip()
        if '://' not in values['proxy'] and values['proxy'].count(':')>=3:
            from urllib.parse import quote
            host,port,user,secret=values['proxy'].split(':',3)
            values['proxy']='http://'+quote(user,safe='')+':'+quote(secret,safe='')+'@'+host+':'+port
        from test_orchestrator import proxy_config
        try: proxy_config(values['proxy'])
        except ValueError:
            QMessageBox.warning(self,'Прокси','Формат: http://user:password@host:port'); return
        if account is None:
            self.settings['accounts'].append({'id':uuid.uuid4().hex,'site_id':site['id'],**values})
        else: account.update(values)
        self.save(); self.refresh_accounts()
    def selected_account(self):
        row=self.table.currentRow(); return self.account_rows[row] if 0<=row<len(self.account_rows) else None
    def edit_account(self):
        if a:=self.selected_account(): self.account_dialog(a)
    def remove_account(self):
        if a:=self.selected_account(): self.settings['accounts'].remove(a); self.save(); self.refresh_accounts()
    def update_engine_label(self):
        engine=self.settings.get('engine',''); self.engine_label.setText('Движок: '+(Path(engine).name if engine else 'встроенный ScopaEngine'))
    def choose_engine(self):
        path,_=QFileDialog.getOpenFileName(self,'Математический движок','','Программа (*.exe)')
        if path: self.settings['engine']=path; self.save(); self.update_engine_label()
    def clear_engine(self): self.settings['engine']=''; self.save(); self.update_engine_label()
    def demo(self,vision=False):
        site=next((s for s in self.settings['sites'] if s.get('demo')),None)
        if site is None:
            site={'id':uuid.uuid4().hex,'name':'Встроенное демо','url':'http://127.0.0.1:5000/demo',
                  'login_url':'http://127.0.0.1:5000/demo','demo':True,**DEFAULTS}; self.settings['sites'].append(site)
        if not any(a['site_id']==site['id'] for a in self.settings['accounts']):
            from workflow_demo import USER,PASSWORD
            self.settings['accounts'].append({'id':uuid.uuid4().hex,'site_id':site['id'],'login':USER,'password':PASSWORD,'proxy':''})
        site.update(DEFAULTS); site['demo']=True;site['workflow_demo']=True
        site['vision_demo']=vision;site['strategy']='vision' if vision else 'text'
        site['goal']='фишки: 10' if vision else 'игра: Scopa; комната: Учебная; стол: 5; фишки: 10'
        self.save(); self.reload_sites(site['id']); self.update_engine_label(); self.start()
    def show_outcome(self,sid,data):
        move=data['move']; before=data['before']; after=data['after']; a=data['analysis']
        self.decision.setText(f"Сессия {sid[:8]}: {move['played_card']} → {', '.join(move['captured_cards']) or 'без захвата'}. "
            f"Накоплено карт: {len(before['captured_cards']['player'])} → {len(after['captured_cards']['player'])}. "
            f"Источник: {a.get('source','внешний движок')}; глубина {a.get('search_depth','—')}. "
            'Ход подтверждён и проверен. В браузере можно повторить или сменить пример.')
    def busy(self, running):
        for widget in (self.sites,self.add_site_button,self.site_settings_button,self.add_account_button,
            self.edit_account_button,self.remove_account_button,self.engine_button,self.demo_engine_button,self.demo_button,self.vision_demo_button,self.stealth,self.goal,self.save_goal_button): widget.setEnabled(not running)
        self.start_button.setEnabled(not running); self.stop_button.setEnabled(running)
        self.work_button.setEnabled(running); self.pause_button.setEnabled(running)
    def begin_work(self):
        account=self.selected_account()
        if account is None:
            self.append_log('Выбери сессию в таблице, затем нажми «Начать работу».'); return
        if account['id'] in self.controls:
            self.controls[account['id']].set()
            self.append_log('Разрешён запуск работы выбранной сессии. Проверяю игровой стол…')
    def pause_work(self):
        account=self.selected_account()
        if account and account['id'] in self.controls:
            self.controls[account['id']].clear()
            self.append_log('Пауза выбранной сессии. Начатый ход завершится, новых ходов не будет. Браузер остаётся открытым.')
    def start(self):
        if self.thread and self.thread.is_alive(): return
        site=self.current_site()
        if not site or not self.account_rows:
            QMessageBox.information(self,'Аккаунты','Добавь сайт и хотя бы один аккаунт.'); return
        if not site.get('demo'):site.update(strategy='vision',launch_mode='auto',login_mode='auto',open_login_selector='')
        site['goal']=self.goal.text().strip()
        if site.get('launch_mode','auto')=='auto' and not site.get('demo') and any(a.get('login') and not a.get('password') for a in self.account_rows):
            QMessageBox.warning(self,'Аккаунты','У аккаунта указан логин, но нет пароля. Нажми «Изменить» и заполни пароль.');return
        self.save(); self.busy(True); self.stop_event.clear(); self.note.setText('Запускаю…')
        self.controls={a['id']:threading.Event() for a in self.account_rows}
        if (site.get('launch_mode','auto')=='auto' and not site.get('demo')) or site.get('workflow_demo'):
            for control in self.controls.values():control.set()
        if self.account_rows and self.table.currentRow()<0: self.table.selectRow(0)
        path=self.directory/'bot_log.txt'; self.log_offset=path.stat().st_size if path.exists() else 0
        data=json.loads(json.dumps({'site':site,'accounts':self.account_rows,'engine':self.settings.get('engine',''),
                                   'stealth':self.stealth.isChecked()}))
        self.thread=threading.Thread(target=self.background,args=(data,),daemon=False); self.thread.start()
    def background(self, data):
        error=''
        try: asyncio.run(run_system(data,self.directory,self.stop_event,self.events,self.controls))
        except Exception as exc:
            error=str(exc) if isinstance(exc,ValueError) else f'Ошибка {type(exc).__name__}. Проверь настройки и наличие браузера.'
        finally: self.events.finished.emit(error)
    def stop(self): self.stop_event.set(); self.stop_button.setEnabled(False); self.note.setText('Закрываю браузеры…')
    def finished(self,error):
        if self.thread: self.thread.join(timeout=.2)
        self.busy(False); self.note.setText(error or 'Остановлено. Можно изменить настройки и запустить снова.')
        if error: self.append_log(error)
        if self.closing: self.close()
    def append_log(self,text): self.log.appendPlainText(text)
    def poll_log(self):
        path=self.directory/'bot_log.txt'
        if not path.exists(): return
        try:
            with path.open('rb') as file:
                if path.stat().st_size<self.log_offset: self.log_offset=0
                file.seek(self.log_offset); lines=file.read().decode('utf-8',errors='replace').splitlines(); self.log_offset=file.tell()
            for line in lines:
                self.append_log(line)
                for row,account in enumerate(self.account_rows):
                    if f'session="{account["id"]}"' in line:
                        status=line.split('status=',1)[1].split()[0] if 'status=' in line else None
                        if status:
                            self.table.item(row,2).setText(STATUS.get(status,status))
                            math_status={'engine_ready':'Підключено','analyzing':'Розрахунок','acting':'Виконує хід',
                                'completed':'Підключено','cancelled':'Вимкнено','failed':'Вимкнено',
                                'browser_closed':'Вимкнено','starting':'Очікує кімнату','waiting_room':'Очікує кімнату',
                                'waiting_table':'Очікує стіл','table_locked':'Перевіряє стан','table_changed':'Хід зупинено'}.get(status)
                            if math_status:self.table.item(row,3).setText(math_status)
        except OSError: pass
    def closeEvent(self,event):
        if self.thread and self.thread.is_alive():
            self.closing=True; self.stop(); event.ignore()
        else:
            self.save(); event.accept()

def main():
    if '--stagehand-self-test' in sys.argv:
        from stagehand_agent import self_test as agent_self_test
        return agent_self_test(Path(sys.argv[sys.argv.index('--stagehand-self-test')+1]).resolve())
    if '--vision-check' in sys.argv:
        from vision_check import run
        return run(Path(sys.argv[sys.argv.index('--vision-check')+1]).resolve())
    os.environ['PLAYWRIGHT_BROWSERS_PATH']='0'
    if '--self-test' in sys.argv:
        return self_test(Path(sys.argv[sys.argv.index('--self-test')+1]).resolve())
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    app=QApplication(sys.argv); app.setApplicationName('QA Manager')
    font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf'
    if font_path.is_file(): QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont('Segoe UI',10))
    window=None
    try:
        window=MainWindow(root/'QA_data'); window.show()
    except Exception as exc:
        QMessageBox.critical(None,'QA Manager',f'Не удалось загрузить настройки: {type(exc).__name__}.\n'
            'Проверь доступ на запись к папке программы. Сохранённые аккаунты доступны только тому же пользователю Windows.')
        return 1
    return app.exec()

def self_test(report):
    """Packaged-app verification; never reads saved user accounts."""
    os.environ['QT_QPA_PLATFORM']='offscreen'
    directory=report.parent/('qa-selftest-'+uuid.uuid4().hex)
    directory.mkdir(parents=True)
    result={'passed':False,'checks':[]}
    try:
        app=QApplication([])
        font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf'
        if font_path.exists(): QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont('Segoe UI',10))
        site={'id':'demo','name':'Встроенное демо','url':'http://127.0.0.1:5000/demo','demo':True,**DEFAULTS,'cdp_headless':True}
        accounts=[{'id':f'qa-{i}','site_id':'demo','login':'','password':'selftest-secret','proxy':''} for i in range(2)]
        data={'sites':[site],'accounts':accounts,'engine':'','stealth':False}
        store=SettingsStore(directory); store.save(data)
        assert store.load()==data
        assert 'selftest-secret' not in store.path.read_text(encoding='utf-8')
        result['checks'].append('DPAPI encrypted settings round-trip')
        window=MainWindow(directory); window.show(); app.processEvents()
        window.grab().save(str(directory/'window.png')); window.close()
        result['checks'].append('GUI render')
        from playwright.async_api import BrowserType
        original=BrowserType.launch
        async def hidden_launch(self,*args,**kwargs):
            kwargs['headless']=True
            return await original(self,*args,**kwargs)
        BrowserType.launch=hidden_launch
        class Messages:
            def emit(self,text): pass
        class TestEvents:
            message=Messages()
        async def verify():
            from playwright.async_api import async_playwright
            from auto_login import authenticate
            async with async_playwright() as p:
                browser=await p.chromium.launch(channel='chrome',headless=True)
                page=await browser.new_page()
                form='<form id="login"><label>Email<input type="email" autocomplete="username"></label><input type="password" autocomplete="current-password"><button type="submit">Войти</button></form>'
                script='''<script>document.querySelector('#login').onsubmit=e=>{e.preventDefault();window.entered=[document.querySelector('input[type=email]').value,document.querySelector('input[type=password]').value];document.body.innerHTML='<button>Выйти</button>';}</script>'''
                html=''
                async def route(r): await r.fulfill(content_type='text/html; charset=utf-8',body='<meta charset="utf-8">'+html)
                await page.route('https://qa.example.test/**',route)
                for modal in (False,True):
                    html=(('<button id="open">Войти</button><div role="dialog" hidden>'+form+'</div>'+script+
                          '<script>document.querySelector("#open").onclick=()=>document.querySelector("[role=dialog]").hidden=false;</script>') if modal else form+script)
                    await authenticate(page,{'mode':'auto'},login_url='https://qa.example.test/',username='test@example.test',password='qa-only')
                    assert await page.evaluate('window.entered')==['test@example.test','qa-only']
                await browser.close()
            result['checks'].append('Automatic direct login and homepage-button modal login with confirmed success')
            stop=threading.Event()
            task=asyncio.create_task(run_system({'site':site,'accounts':accounts,'engine':'','stealth':False},directory,stop,TestEvents()))
            try:
                async with asyncio.timeout(45):
                    while True:
                        path=directory/'bot_log.txt'
                        text=path.read_text(encoding='utf-8') if path.exists() else ''
                        if all(f'session="qa-{i}" status=completed' in text for i in range(2)): break
                        if task.done():
                            await task
                            raise RuntimeError('Sessions stopped before completing a cycle')
                        await asyncio.sleep(.1)
                for i in range(2):
                    outcome=json.loads((directory/f'last_move_qa-{i}.json').read_text(encoding='utf-8'))
                    assert outcome['analysis']['source']=='Scopa DecisionEngine'
                    assert not outcome['analysis']['fallback']
                    assert set(outcome['move']['captured_cards'])=={'coppe:1','denari:7'}
                    assert outcome['after']['captured_cards']['player']==['coppe:1','coppe:8','denari:7'] or set(outcome['after']['captured_cards']['player'])=={'coppe:1','coppe:8','denari:7'}
                    assert len(outcome['analysis']['alternatives'])==3
                result['checks'].append('2 isolated tables -> full state -> real EXE -> hand/capture clicks -> confirmed legal transition')
            finally:
                stop.set(); await asyncio.wait_for(task,35)
                logging.shutdown()
        asyncio.run(verify())
        async def verify_manual():
            manual_directory=directory/'manual'; manual_directory.mkdir()
            control=threading.Event(); stop=threading.Event()
            manual_site={**site,'demo':False,'launch_mode':'manual','strategy':'text','url':'http://127.0.0.1:5000/demo?sid=manual-selftest'}
            account={'id':'manual-selftest','login':'NOT-AUTO-LOGIN','password':'DO-NOT-FILL','proxy':''}
            task=asyncio.create_task(run_system({'site':manual_site,'accounts':[account],'engine':'','stealth':False},manual_directory,stop,TestEvents(),{'manual-selftest':control}))
            try:
                async with asyncio.timeout(45):
                    path=manual_directory/'bot_log.txt'
                    while not path.exists() or 'status=waiting_user' not in path.read_text(encoding='utf-8'):
                        if task.done(): await task;raise AssertionError('Manual session ended before waiting')
                        await asyncio.sleep(.1)
                    await asyncio.sleep(1)
                    assert not (manual_directory/'last_move_manual-selftest.json').exists()
                    control.set()
                    while 'status=completed' not in path.read_text(encoding='utf-8'):
                        if task.done(): await task;raise AssertionError('Manual session failed')
                        await asyncio.sleep(.1)
                    control.clear()
                result['checks'].append('Manual browser launch ignores saved credentials; no move before Start; real capture after Start')
            finally:
                stop.set();await asyncio.wait_for(task,35)
        asyncio.run(verify_manual())
        async def verify_workflow():
            workflow_directory=directory/'workflow';workflow_directory.mkdir()
            stop=threading.Event()
            workflow_site={**site,'demo':True,'workflow_demo':True,'launch_mode':'auto',
                'goal':'игра: Scopa; комната: Учебная; стол: 5; фишки: 10','strategy':'text'}
            account={'id':'wf-packaged','login':'','password':'','proxy':''}
            task=asyncio.create_task(run_system({'site':workflow_site,'accounts':[account],'engine':'','stealth':False},workflow_directory,stop,TestEvents()))
            try:
                async with asyncio.timeout(50):
                    path=workflow_directory/'bot_log.txt'
                    while not path.exists() or 'status=completed' not in path.read_text(encoding='utf-8'):
                        if task.done():await task;raise AssertionError('Full workflow ended before completion')
                        await asyncio.sleep(.1)
                    text=path.read_text(encoding='utf-8')
                    assert 'Вход подтверждён' in text and 'Сесть' in text and 'Сделать ставку' in text
                    assert text.index('Сделать ставку')<text.index('status=analyzing')
                    outcome=json.loads((workflow_directory/'last_move_wf-packaged.json').read_text(encoding='utf-8'))
                    assert set(outcome['move']['captured_cards'])=={'coppe:1','denari:7'}
                result['checks'].append('Automatic account login -> game -> room -> exact table -> seat -> confirmed virtual bet -> real engine move')
            finally:
                stop.set();await asyncio.wait_for(task,35)
        asyncio.run(verify_workflow())
        result['checks'].append('Browser and server shutdown')
        result['passed']=True
    except BaseException as exc:
        import traceback
        result['error']=traceback.format_exc()
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
