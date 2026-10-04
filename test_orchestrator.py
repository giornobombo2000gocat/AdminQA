"""Visible, independently supervised async Playwright QA sessions. Python 3.11+."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import queue
import random
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright
from card_qa import CardQA, Config, StaleSnapshotError
from scopa_qa import ScopaQA, WaitingForTurn, TableChangedError
from stealth_config import apply_stealth, choose_user_agent, random_human_delay, smooth_click
from auto_login import authenticate, authenticated, LoginOriginError, LoginDiscoveryError
from room_agent import RoomAgent, AgentError, AgentPaused, WaitingForTable


def proxy_config(address):
    if not address:
        return None
    p = urlparse(address)
    if p.scheme not in {'http', 'https', 'socks5'} or not p.hostname or not p.port:
        raise ValueError('Invalid proxy URL')
    host = f'[{p.hostname}]' if ':' in p.hostname else p.hostname
    result = {'server': f'{p.scheme}://{host}:{p.port}'}
    if p.username is not None:
        if p.scheme == 'socks5':
            raise ValueError('Authenticated SOCKS5 unsupported')
        result.update(username=unquote(p.username), password=unquote(p.password or ''))
    return result


def origin(url):
    p = urlparse(url)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
        raise ValueError('Invalid session URL')
    return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)


def credential(config, name):
    env_key = config.get(name + '_env')
    return os.environ[env_key] if env_key else config[name]



def require_local_demo(url):
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('This source distribution supports local QA demo URLs only.')
    if parsed.username or parsed.password:
        raise ValueError('Credentials in demo URLs are not supported.')

async def local_demo_route(route):
    try:
        require_local_demo(route.request.url)
    except ValueError:
        await route.abort()
    else:
        await route.continue_()


class TestOrchestrator:
    def __init__(self, config_path='config.json', *, config_data=None):
        self.config_path = Path(config_path).resolve()
        self.config = (config_data if config_data is not None else
                       json.loads(self.config_path.read_text(encoding='utf-8')))
        self.sessions = self.config['sessions']
        for item in self.sessions:
            require_local_demo(item['url'])
            if item.get('auth', {}).get('url'):
                require_local_demo(item['auth']['url'])
        self.stealth_enabled = bool(self.config.get('stealth_enabled', True))
        self.manual_login = bool(self.config.get('manual_login',self.config.get('manual_start',False)))
        if not self.sessions:
            raise ValueError('sessions must not be empty')
        ids = [s['id'] for s in self.sessions]
        if any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)):
            raise ValueError('Session IDs must be nonempty and unique')
        self.interval = float(self.config.get('interval_seconds', 1))
        self.cycle_timeout = float(self.config.get('cycle_timeout_seconds', 45))
        self.setup_timeout = float(self.config.get('setup_timeout_seconds', 60))
        self.max_errors = int(self.config.get('max_consecutive_errors', 5))
        starts = int(self.config.get('parallel_startups', 2))
        if min(self.cycle_timeout, self.setup_timeout, self.max_errors, starts) <= 0 or self.interval < 0:
            raise ValueError('Invalid timeout/limit settings')
        self.adapter_config = Config(**{'api_url': 'http://localhost:5000/analyze',
                                       **self.config.get('dom', {})})
        if self.adapter_config.mode not in {'cards','scopa','agent'}:
            raise ValueError('DOM mode must be cards, scopa or agent')
        api = urlparse(self.adapter_config.api_url)
        if api.hostname not in {'localhost', '127.0.0.1', '::1'} or api.port != 5000:
            raise ValueError('Analysis API must be localhost:5000')
        for session in self.sessions:
            if session.get('browser', 'chromium') not in {'chromium', 'firefox', 'random'}:
                raise ValueError('browser must be chromium, firefox or random')
            origin(session['url'])
            proxy_config(session.get('proxy'))
            auth = session.get('auth')
            if auth and not self.manual_login:
                origin(auth.get('url', session['url']))
                for name in ('username', 'password'):
                    credential(auth, name)
                if auth.get('mode','auto')=='manual':
                    for name in ('username_selector', 'password_selector', 'submit_selector', 'success_selector'):
                        if not auth.get(name): raise ValueError(f'Auth requires {name}')
        self.start_gate = asyncio.Semaphore(starts)
        self.tasks = {}
        self.browsers = {}
        self.status = {i: 'pending' for i in ids}
        self._stop = asyncio.Event()
        self._running = False
        self._used = False
        self.logger = logging.getLogger(f'TestOrchestrator.{id(self)}')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    def _start_logging(self):
        path = self.config_path.parent / self.config.get('log_file', 'bot_log.txt')
        path.parent.mkdir(parents=True, exist_ok=True)
        output = logging.FileHandler(path, encoding='utf-8')
        output.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        messages = queue.SimpleQueue()
        self._queue_handler = logging.handlers.QueueHandler(messages)
        self.logger.addHandler(self._queue_handler)
        self._listener = logging.handlers.QueueListener(messages, output)
        self._file_handler = output
        self._listener.start()

    def _set_status(self, sid, state, **details):
        self.status[sid] = state
        # Do not log URLs, commands, DOM payloads, passwords or exception text.
        detail = ' '.join(f'{k}={v}' for k, v in details.items())
        self.logger.info('session=%s status=%s %s', json.dumps(sid), state, detail)

    async def _authenticate(self, page, session, resume=False, request=None, state=None):
        auth = session.get('auth')
        if not auth:
            return
        await authenticate(page,{**auth,'_resume':resume},login_url=auth.get('url',session['url']),
            username=credential(auth,'username'),password=credential(auth,'password'),
            vision_request=request,session_state=state,
            notify=lambda message:self.logger.info('session=%s diagnostic=%s',json.dumps(session['id']),message))

    async def _worker(self, p, session):
        sid = session['id']
        browser = context = request = None
        cdp_owner=None
        stage = 'starting'
        completed = failures = 0
        auth_pending=False
        auth_state={}
        awaiting_login_result=False
        engine_ready=False
        navigator=None
        waiting_table_logged=False
        try:
            self._set_status(sid, stage)
            async with self.start_gate:
                async with asyncio.timeout(self.setup_timeout):
                    kwargs = {'headless': False}
                    if session.get('browser_channel'):
                        kwargs['channel'] = session['browser_channel']
                    engine = session.get('browser', 'chromium')
                    if engine == 'random':
                        engine = random.choice(['chromium', 'firefox'])
                    proxy = proxy_config(session.get('proxy'))
                    if proxy:
                        kwargs['proxy'] = proxy
                    if session.get('connection_mode')=='cdp':
                        if engine!='chromium':raise ValueError('CDP требует Chromium.')
                        if session.get('browser_channel')=='shard':
                            from shard_browser import ShardBrowser
                            cdp_owner=ShardBrowser(self.config['shard_sdk'],sid,
                                proxy=session.get('proxy'),headless=session.get('cdp_headless',False))
                        else:
                            from cdp_browser import CDPBrowser
                            cdp_owner=CDPBrowser(self.config_path.parent/'browser_profiles',sid,
                                session.get('browser_channel','chrome'),session.get('cdp_headless',False))
                        browser=await cdp_owner.start(p)
                        self.logger.info('session=%s connection=cdp endpoint=%s',json.dumps(sid),cdp_owner.endpoint)
                    else:browser = await getattr(p, engine).launch(**kwargs)
                    self.browsers[sid] = browser
                    options = {}
                    native_shard=session.get('browser_channel')=='shard'
                    if cdp_owner and proxy and not native_shard:options['proxy']=proxy
                    if session.get('user_agent'):
                        options['user_agent'] = session['user_agent']
                    elif self.stealth_enabled:
                        options['user_agent'] = choose_user_agent(engine, browser.version)
                    context = browser.contexts[0] if native_shard else await browser.new_context(**options)
                    if self.stealth_enabled and not native_shard:
                        await apply_stealth(context, engine=engine)
                    self._set_status(sid, 'browser_ready', engine=engine)
                    await context.route('**/*', local_demo_route)
                    page = await context.new_page()
                    if cdp_owner:
                        for other_context in browser.contexts:
                            if other_context is not context:
                                for blank in other_context.pages:
                                    if blank.url=='about:blank':await blank.close()
                    headers=({'X-QA-Session':sid,'X-QA-Token':self.config['engine_gate_token']} if self.config.get('engine_gate_token') else {})
                    request = await p.request.new_context(extra_http_headers=headers)
                    page.set_default_timeout(self.adapter_config.timeout_ms)
                    stage = 'authenticating' if session.get('auth') and not self.manual_login else 'navigating'
                    self._set_status(sid, stage)
                    if not self.manual_login:
                        try:
                            await self._authenticate(page, session,request=request,state=auth_state)
                            if session.get('auth'):self._set_status(sid,'authenticated')
                        except LoginDiscoveryError as exc:
                            if not self.config.get('manual_start'):raise
                            auth_pending=True
                            awaiting_login_result=str(exc)=='login_not_confirmed'
                            getattr(self,'clear_start',lambda _:None)(sid)
                            detail={'login_access_denied':'Сайт отказал в доступе: HTTP 403','login_rate_limited':'Сайт ограничил запросы: HTTP 429'}.get(str(exc),str(exc))
                            network_help={
                                'ERR_PROXY_CONNECTION_FAILED':'Не вдалося з’єднатися з проксі. Перевір адресу, порт і доступність проксі.',
                                'ERR_TUNNEL_CONNECTION_FAILED':'Проксі не створив HTTPS-з’єднання. Перевір авторизацію та підтримку HTTPS.',
                                'ERR_INVALID_AUTH_CREDENTIALS':'Відхилені дані авторизації проксі або сервера.',
                                'ERR_NO_SUPPORTED_PROXIES':'Непідтримуваний тип проксі.',
                                'ERR_NAME_NOT_RESOLVED':'Не вдалося визначити IP-адресу сайту або проксі.',
                                'ERR_CONNECTION_REFUSED':'Сервер або проксі відхилив з’єднання.',
                                'ERR_CONNECTION_RESET':'З’єднання обірвано сервером або проксі.',
                                'ERR_CERT_AUTHORITY_INVALID':'Недовірений сертифікат HTTPS. Перевір сайт або проксі.'}
                            if str(exc).startswith('navigation_'):
                                code=str(exc).removeprefix('navigation_')
                                detail=code+' — '+network_help.get(code,'Не вдалося відкрити сторінку. Перевір адресу та мережеве з’єднання.')
                                self.logger.error('session=%s diagnostic=%s',json.dumps(sid),detail)
                            self.logger.warning('session=%s diagnostic=Вход не распознан (%s). Браузер оставлен открытым. Открой форму или войди вручную, затем нажми «Начать работу».',json.dumps(sid),detail)
                    stage = 'navigating'
                    self._set_status(sid, stage)
                    response = None
                    if not auth_pending and (self.manual_login or not session.get('auth') or not (self.config.get('room_agent',{}).get('goal') or self.config.get('room_agent',{}).get('auto_discover'))):
                        response = await page.goto(session['url'], wait_until='domcontentloaded')
                    if response is not None and response.status >= 400:
                        if not self.config.get('manual_start'):
                            raise RuntimeError('Navigation HTTP error')
                        self.logger.warning('session=%s diagnostic=Страница вернула HTTP %s. Браузер оставлен открытым для ручной проверки.',json.dumps(sid),response.status)
                    # Per-session API context, independent of browser cookies/proxy.
            adapter_class = ScopaQA if self.adapter_config.mode == 'scopa' else CardQA
            adapter = None
            announced_wait = False
            while not self._stop.is_set():
                manual = self.config.get('manual_start',False)
                enabled = lambda: not manual or getattr(self,'start_requested',lambda _:False)(sid)
                if not enabled():
                    # Late SPA login completion is observed, never resubmitted.
                    if auth_pending and awaiting_login_result and not page.is_closed():
                        auth=session.get('auth',{})
                        evidence=await authenticated(page,auth,auth.get('url',session['url']),credential(auth,'username'))
                        if evidence:
                            auth_state['confirmed']=True;auth_pending=False;awaiting_login_result=False
                            self._set_status(sid,'authenticated')
                            self.logger.info('session=%s diagnostic=Вхід підтверджено після очікування (%s). Продовжую пошук Scopa.',json.dumps(sid),evidence)
                            getattr(self,'resume_start',lambda _:None)(sid)
                            continue
                    if not announced_wait:
                        self._set_status(sid,'waiting_user')
                        message=('Войди вручную, открой игровой стол и нажми «Начать работу» для этой сессии.' if self.manual_login else
                            'Автоматический цикл приостановлен. Проверь страницу и нажми «Начать работу» для продолжения выбранной сессии.')
                        self.logger.info('session=%s diagnostic=%s',json.dumps(sid),message)
                        announced_wait=True
                    if not context.pages:
                        self._set_status(sid,'browser_closed');return
                    await asyncio.sleep(1 if awaiting_login_result else .2)
                    continue
                if adapter is None:
                    if auth_pending:
                        try:
                            async with asyncio.timeout(self.setup_timeout):await self._authenticate(page,session,resume=True,request=request,state=auth_state)
                            auth_pending=False
                            awaiting_login_result=False
                            self._set_status(sid,'authenticated')
                        except LoginDiscoveryError as exc:
                            getattr(self,'clear_start',lambda _:None)(sid)
                            self.logger.warning('session=%s diagnostic=Вход пока не подтверждён (%s). Браузер остаётся открытым.',json.dumps(sid),str(exc))
                            continue
                    if manual:
                        if not waiting_table_logged:self._set_status(sid,'checking_room')
                        pages=[p for p in context.pages if not p.is_closed()]
                        focused=[]
                        for candidate in pages:
                            try:
                                if await candidate.evaluate('document.hasFocus()'): focused.append(candidate)
                            except Exception: pass
                        page=(focused or pages)[-1] if pages else None
                        if page is None:
                            self._set_status(sid,'browser_closed');return
                        agent_config=self.config.get('room_agent',{})
                        if agent_config.get('goal') or agent_config.get('auto_discover') or self.adapter_config.mode=='agent':
                            if not waiting_table_logged:self._set_status(sid,'agent_searching')
                            if navigator is None or navigator.page.is_closed():
                                navigator=RoomAgent(page,request,agent_config,enabled=enabled,
                                    notify=lambda msg:self.logger.info('session=%s diagnostic=%s',json.dumps(sid),msg))
                            agent=navigator
                            try:
                                if self.adapter_config.mode=='agent':
                                    adapter=agent
                                else:
                                    selector=(self.adapter_config.state_selector if self.adapter_config.mode=='scopa' else self.adapter_config.card_selector)
                                    await agent.navigate(selector)
                                    page=agent.page
                            except WaitingForTable as exc:
                                if not waiting_table_logged:
                                    self._set_status(sid,'waiting_table')
                                    self.logger.info('session=%s diagnostic=%s',json.dumps(sid),str(exc))
                                    waiting_table_logged=True
                                await asyncio.sleep(2);continue
                            except AgentError as exc:
                                self._set_status(sid,'waiting_room')
                                self.logger.info('session=%s diagnostic=%s',json.dumps(sid),str(exc))
                                getattr(self,'clear_start',lambda _:None)(sid)
                                await asyncio.sleep(.3);continue
                        if self.adapter_config.mode=='agent':
                            announced_wait=False
                            continue
                        frames=[]
                        selector=(self.adapter_config.state_selector if self.adapter_config.mode=='scopa'
                                  else self.adapter_config.card_selector)
                        for frame in page.frames:
                            try:
                                if await frame.locator(selector).count(): frames.append(frame)
                            except Exception: pass
                        if len(frames)!=1:
                            self._set_status(sid,'waiting_room')
                            self.logger.info('session=%s diagnostic=Игровой стол не распознан однозначно. Открой нужную вкладку и проверь настройки сбора состояния, затем нажми «Начать работу» ещё раз.',json.dumps(sid))
                            getattr(self,'clear_start',lambda _:None)(sid)
                            await asyncio.sleep(.3)
                            continue
                        room_frame=frames[0]
                    else:
                        room_frame=page.main_frame
                    adapter=adapter_class(page,self.adapter_config,frame=room_frame,request_context=request,
                        click_handler=smooth_click if self.stealth_enabled else None)
                    if manual:
                        try: await adapter.extract_data()
                        except WaitingForTurn: pass
                        except Exception:
                            adapter=None
                            self._set_status(sid,'waiting_room')
                            self.logger.info('session=%s diagnostic=На странице нет корректного полного состояния игры. Проверь адаптер и настройки сайта. Браузер оставлен открытым.',json.dumps(sid))
                            getattr(self,'clear_start',lambda _:None)(sid)
                            await asyncio.sleep(.3)
                            continue
                    announced_wait=False
                    self._set_status(sid,'table_locked')
                    self.logger.info('session=%s diagnostic=Стіл зафіксовано. Навігацію завершено; очікую повний стан і свій хід.',json.dumps(sid))
                stage = 'collecting'
                try:
                    async with asyncio.timeout(self.cycle_timeout):
                        if isinstance(adapter,RoomAgent):
                            stage='agent_playing';self._set_status(sid,stage)
                            await adapter.play_step()
                            completed+=1;failures=0
                            await asyncio.sleep(self.interval)
                            continue
                        self._set_status(sid, stage)
                        if self.config.get('ready_selector'):
                            await page.locator(self.config['ready_selector']).wait_for(state='visible')
                        if self.adapter_config.mode=='scopa':
                            betting=RoomAgent(page,request,self.config.get('room_agent',{}),enabled=enabled,
                                notify=lambda msg:self.logger.info('session=%s diagnostic=%s',json.dumps(sid),msg))
                            await betting.place_requested_bet(adapter.root,self.adapter_config.state_selector)
                        payload = await adapter.extract_data()
                        if not enabled(): continue
                        if self.config.get('engine_gate_url') and not engine_ready:
                            response=await request.post(self.config['engine_gate_url'],data=payload,timeout=5000,max_redirects=0)
                            try:
                                if not response.ok:raise AgentError('Математичний движок не отримав підтвердження готовності кімнати.')
                            finally:await response.dispose()
                            engine_ready=True
                            self._set_status(sid,'engine_ready')
                            self.logger.info('session=%s diagnostic=Кімната та стан гри підтверджені. Підключаю математичний движок.',json.dumps(sid))
                        if self.stealth_enabled:
                            await random_human_delay()
                        stage = 'analyzing'
                        self._set_status(sid, stage)
                        command = await adapter.sync_data(payload)
                        if self.stealth_enabled:
                            await random_human_delay()
                        if not enabled(): continue
                        stage = 'acting'
                        self._set_status(sid, stage)
                        await adapter.execute_action(command)
                        callback = getattr(self, 'on_outcome', None)
                        if callback and hasattr(adapter, 'outcome'):
                            callback(sid, adapter.outcome)
                    completed += 1
                    failures = 0
                    self._set_status(sid, 'completed', cycles=completed)
                    await asyncio.sleep(self.interval)
                except AgentError as exc:
                    self._set_status(sid,'waiting_room')
                    self.logger.info('session=%s diagnostic=%s',json.dumps(sid),str(exc))
                    getattr(self,'clear_start',lambda _:None)(sid)
                    adapter=None
                except TableChangedError as exc:
                    getattr(self,'clear_start',lambda _:None)(sid)
                    if engine_ready and self.config.get('engine_gate_url'):
                        response=await request.post(self.config['engine_gate_url'].removesuffix('/room-ready')+'/room-left',timeout=1500,max_redirects=0)
                        await response.dispose();engine_ready=False
                    self._set_status(sid,'table_changed')
                    self.logger.error('session=%s diagnostic=%s',json.dumps(sid),str(exc))
                    if not manual:return
                    continue
                except WaitingForTurn:
                    failures = 0
                    self._set_status(sid, 'waiting_turn')
                    await asyncio.sleep(max(1,self.interval))
                except StaleSnapshotError:
                    failures += 1
                    self._set_status(sid, 'stale_snapshot', errors=failures)
                except Exception as exc:
                    failures += 1
                    if isinstance(adapter,RoomAgent):
                        self._set_status(sid,'waiting_room')
                        self.logger.info('session=%s diagnostic=Результат действия ИИ не подтверждён. Проверь страницу вручную, прежде чем возобновлять работу.',json.dumps(sid))
                        getattr(self,'clear_start',lambda _:None)(sid)
                        adapter=None;failures=0
                        continue
                    if stage == 'acting':
                        self._set_status(sid, 'action_outcome_unknown', error=type(exc).__name__)
                        return
                    self._set_status(sid, 'retrying', stage=stage, error=type(exc).__name__, errors=failures)
                if failures:
                    if failures >= self.max_errors:
                        self._set_status(sid, 'error_limit_reached')
                        return
                    await asyncio.sleep(min(30, 2 ** failures))
        except asyncio.CancelledError:
            self._set_status(sid, 'cancelled')
            raise
        except Exception as exc:
            reason = (str(exc) if isinstance(exc,LoginDiscoveryError) else
                      'login_origin_changed' if isinstance(exc, LoginOriginError) else
                      'page_timeout' if type(exc).__name__ == 'TimeoutError' else 'setup_error')
            self._set_status(sid, 'failed', stage=stage, error=type(exc).__name__, reason=reason)
            messages = {
                'login_origin_changed': 'Страница входа перенаправила на другой домен или протокол. '
                    'Укажи конечный адрес формы в «Настройки сайта → Страница входа». '
                    'Ввод пароля остановлен до проверки адреса.',
                'page_timeout': 'Истекло время ожидания страницы или формы входа. Проверь прокси, адрес и селекторы.',
                'setup_error': 'Не удалось подготовить сессию. Проверь адреса страниц, настройки входа и прокси.'}
            messages.update({
                'ambiguous_login':'Найдено несколько вариантов входа. Укажи селектор кнопки/полей в настройках сайта.',
                'login_button_not_found':'Не найдена кнопка входа. Укажи «Кнопка открытия входа» в настройках сайта.',
                'login_form_not_found':'Не найдена подходящая форма входа. Проверь селекторы или открой форму вручную.',
                'login_not_confirmed':'Вход не подтверждён. Проверь аккаунт и «Признак успешного входа»; возможны CAPTCHA или двухэтапный вход.',
                'login_requires_verification':'Сайт запросил код подтверждения. Автоматический вход остановлен.',
                'too_many_candidates':'Слишком много полей для однозначного выбора. Укажи селекторы формы.',
                'invalid_login_mode':'Режим входа должен быть auto или manual.'})
            self.logger.error('session=%s diagnostic=%s', json.dumps(sid), messages.get(reason,messages['setup_error']))
        finally:
            if engine_ready and request and self.config.get('engine_gate_url'):
                try:
                    response=await request.post(self.config['engine_gate_url'].removesuffix('/room-ready')+'/room-left',timeout=1500,max_redirects=0)
                    await response.dispose()
                except Exception:pass
            # Bounded independent cleanup; continue even if one close fails.
            for resource, method in ((request, 'dispose'), (context, 'close'), (browser, 'close')):
                if resource is not None:
                    try:
                        async with asyncio.timeout(10):
                            await getattr(resource, method)()
                    except Exception as exc:
                        self.logger.warning('session=%s cleanup_error=%s', json.dumps(sid), type(exc).__name__)
            self.browsers.pop(sid, None)
            if cdp_owner:
                try:await cdp_owner.close()
                except Exception as exc:self.logger.warning('session=%s cdp_cleanup_error=%s',json.dumps(sid),type(exc).__name__)
            self.logger.info('session=%s resources_closed=true', json.dumps(sid))

    async def run(self):
        if self._used:
            raise RuntimeError('Create a new orchestrator for another run')
        self._used = self._running = True
        self._start_logging()
        try:
            async with async_playwright() as p:
                self.tasks = {s['id']: asyncio.create_task(self._worker(p, s), name=s['id'])
                              for s in self.sessions}
                try:
                    await asyncio.gather(*self.tasks.values())
                except asyncio.CancelledError:
                    if not self._stop.is_set():
                        raise
                finally:
                    await self.stop()
        finally:
            self._running = False
            self.logger.removeHandler(self._queue_handler)
            await asyncio.to_thread(self._listener.stop)
            self._file_handler.close()

    async def stop(self):
        self._stop.set()
        for task in self.tasks.values():
            if not task.done() and task.cancelling() == 0:
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json')
    args = parser.parse_args()
    try:
        asyncio.run(TestOrchestrator(args.config).run())
    except KeyboardInterrupt:
        pass
