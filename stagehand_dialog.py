"""Qt prompt panel; each task runs in its own bounded asyncio worker."""
import asyncio
import threading
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                              QPlainTextEdit, QPushButton, QHBoxLayout, QLabel)
from stagehand_agent import OllamaModel, PromptAgent, DEFAULT_MODEL


class AgentEvents(QObject):
    message=Signal(str)
    ready=Signal()
    idle=Signal()
    finished=Signal()


class AgentDialog(QDialog):
    def __init__(self, settings, save, parent=None):
        super().__init__(parent)
        self.settings=settings; self.save_settings=save; self.thread=None
        self.loop=None; self.root_task=None; self.queue=None; self.job=None
        self.closing=False; self.ready=False
        self.events=AgentEvents()
        self.events.message.connect(self.append_log)
        self.events.ready.connect(self.on_ready)
        self.events.idle.connect(self.on_idle)
        self.events.finished.connect(self.on_finished)
        self.setWindowTitle('Stagehand • промпты для локального QA')
        self.resize(760,640)
        data=settings.get('prompt_agent',{})
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Агент управляет собственным локальным демо. Правила сохраняются как инструкции, без дообучения весов.'))
        form=QFormLayout()
        self.endpoint=QLineEdit(data.get('endpoint','http://127.0.0.1:11434'))
        self.model=QLineEdit(data.get('model',DEFAULT_MODEL))
        form.addRow('Локальный Ollama:',self.endpoint)
        form.addRow('Установленная модель:',self.model)
        layout.addLayout(form)
        self.rules=QPlainTextEdit(data.get('rules',''))
        self.rules.setPlaceholderText('Постоянные инструкции агенту: например, работай по одному шагу.')
        self.rules.setMaximumHeight(90); layout.addWidget(self.rules)
        self.prompt=QPlainTextEdit(data.get('prompt','Открой карточные игры, выбери Scopa, открой учебную комнату и стол 5.'))
        self.prompt.setMaximumHeight(100); layout.addWidget(self.prompt)
        row=QHBoxLayout()
        self.open_button=QPushButton('Открыть браузер агента'); self.open_button.clicked.connect(self.start)
        self.run_button=QPushButton('Выполнить промпт'); self.run_button.clicked.connect(self.execute)
        self.cancel_button=QPushButton('Отмена'); self.cancel_button.clicked.connect(self.cancel)
        self.reset_button=QPushButton('На главную демо'); self.reset_button.clicked.connect(lambda:self.send('reset'))
        for button in (self.open_button,self.run_button,self.cancel_button,self.reset_button):row.addWidget(button)
        layout.addLayout(row)
        self.output=QPlainTextEdit(); self.output.setReadOnly(True);self.output.setMaximumBlockCount(400)
        layout.addWidget(self.output)
        self.on_idle()

    def append_log(self,text):
        self.output.appendPlainText(text)
        if self.parent() and hasattr(self.parent(),'append_log'):
            self.parent().append_log('Stagehand: '+text)

    def persist(self):
        self.settings['prompt_agent']={'endpoint':self.endpoint.text().strip(),
            'model':self.model.text().strip(),'rules':self.rules.toPlainText(),
            'prompt':self.prompt.toPlainText()}
        self.save_settings()

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.persist(); data=dict(self.settings['prompt_agent'])
        self.open_button.setEnabled(False);self.endpoint.setEnabled(False);self.model.setEnabled(False)
        self.append_log('Подключаю Stagehand и локальную модель…')
        self.thread=threading.Thread(target=self.worker,args=(data,),daemon=True)
        self.thread.start()

    def worker(self,data):
        try:asyncio.run(self.serve(data))
        except asyncio.CancelledError:pass
        except Exception as exc:
            self.events.message.emit(f'Ошибка: {type(exc).__name__}: {str(exc)[:400]}')
        finally:self.events.finished.emit()

    async def serve(self,data):
        self.loop=asyncio.get_running_loop(); self.root_task=asyncio.current_task();self.queue=asyncio.Queue()
        agent=PromptAgent(OllamaModel(data['endpoint'],data['model']),self.events.message.emit)
        try:
            if self.closing:return
            async with asyncio.timeout(90):await agent.start()
            if self.closing:return
            self.events.ready.emit()
            while True:
                command=await self.queue.get()
                self.job=asyncio.create_task(agent.reset() if command[0]=='reset' else agent.execute(command[1],command[2]))
                try:await self.job
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():raise
                    self.events.message.emit('Задача отменена. Уже выполненные действия остаются на странице.')
                except Exception as exc:self.events.message.emit(f'Задача остановлена: {type(exc).__name__}: {str(exc)[:400]}')
                finally:self.job=None;self.events.idle.emit()
        finally:
            await agent.close()
            self.loop=None;self.root_task=None;self.queue=None

    def on_ready(self):
        self.ready=True;self.on_idle()

    def on_idle(self):
        self.run_button.setEnabled(self.ready);self.reset_button.setEnabled(self.ready)
        self.cancel_button.setEnabled(False)

    def send(self,kind):
        if not self.ready or not self.loop:return
        self.persist(); command=(kind,self.prompt.toPlainText(),self.rules.toPlainText())
        self.run_button.setEnabled(False);self.reset_button.setEnabled(False);self.cancel_button.setEnabled(True)
        self.loop.call_soon_threadsafe(self.queue.put_nowait,command)

    def execute(self):self.send('run')

    def cancel(self):
        if self.loop:
            def cancel_job():
                if self.job:self.job.cancel()
            self.loop.call_soon_threadsafe(cancel_job)

    def on_finished(self):
        self.ready=False;self.on_idle();self.open_button.setEnabled(True)
        self.endpoint.setEnabled(True);self.model.setEnabled(True)
        if self.closing:self.accept()

    def closeEvent(self,event):
        self.persist()
        if self.thread and self.thread.is_alive():
            self.closing=True;self.ready=False;self.on_idle();event.ignore()
            if self.loop and self.root_task:self.loop.call_soon_threadsafe(self.root_task.cancel)
        else:event.accept()
