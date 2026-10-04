"""Discover ordinary login forms without guessing through ambiguous UI."""
import asyncio
import re
from urllib.parse import urlparse


class LoginOriginError(ValueError):
    pass


class LoginDiscoveryError(ValueError):
    pass


LOGIN = re.compile(r'^\s*(log\s*in|login|sign\s*in|войти|вход|увійти|увійти в акаунт|войти в аккаунт|личный кабинет|авторизация|авторизоваться|вход в аккаунт|вход в систему|войти на сайт|sign in to your account|accedi|accedi al conto|accedi al tuo account|accesso|entra|effettua accesso|effettua l’accesso|effettua l\'accesso|accedi ora|entra nel tuo account)\s*$',re.I)
SIGNED = re.compile(r'^\s*(log\s*out|sign\s*out|logout|выйти|выход|вийти|my account|мой аккаунт|мій акаунт|esci|disconnetti|il mio conto|il mio account|disconnettiti|mio conto|mio account)\s*$',re.I)


async def authenticated(page,auth,login_url,username=''):
    """Positive account evidence only; a disappearing modal is not enough.

    Return an evidence category, never account text, balance or credentials.
    Observe same-site frames and open shadow roots, including non-button UI.
    """
    if not allowed_origin(login_url,page.url):return None
    signals=[]
    for frame in page.frames:
        if not allowed_origin(login_url,frame.url):continue
        try:
            info=await frame.evaluate('''username=>{
                const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
                const roots=[document],nodes=[];
                for(let i=0;i<roots.length;i++)for(const e of roots[i].querySelectorAll('*')){if(e.shadowRoot)roots.push(e.shadowRoot);nodes.push(e)}
                const out={password:false,otp:false,login:false,logout:false,username:false,member:false,balance:false};
                const norm=s=>(s||'').replace(/\\s+/g,' ').trim().toLowerCase();username=norm(username);
                for(const e of nodes){
                    if(!visible(e))continue;
                    if(e.matches('input[type=password]'))out.password=true;
                    if(e.matches('input[autocomplete="one-time-code"]'))out.otp=true;
                    const label=norm(e.getAttribute('aria-label')||e.getAttribute('title')||e.innerText);
                    const interactive=e.matches('button,a,[role=button],[role=link],[onclick],[tabindex]');
                    const href=e.getAttribute('href')||'';
                    if(interactive&&(/^(log\\s*out|sign\\s*out|logout|esci|disconnetti|disconnettiti|выйти|выход|вийти)$/.test(label)||/[/#?](logout|signout|disconnetti)([/#?=]|$)/i.test(href)))out.logout=true;
                    if(interactive&&/^(accedi(?: ora| al conto| al tuo account)?|accesso|entra|login|log in|sign in|войти|вход|увійти)$/.test(label))out.login=true;
                    if(interactive&&(/^(il mio (conto|account|profilo)|mio (conto|account|profilo)|my account|area personale|profilo|account|мой аккаунт|мій акаунт)$/.test(label)||/account.?menu|user.?menu|profile.?menu/i.test([e.id,e.className,e.getAttribute('data-testid')].join(' '))))out.member=true;
                    if(label.length<100&&/^(saldo|balance|fiches|баланс)\\b/.test(label)&&/\\d/.test(label))out.balance=true;
                    if(username.length>=3&&e.tagName!=='INPUT'&&label.length<username.length+35&&(label===username||label==='ciao, '+username||label==='ciao '+username||label==='benvenuto '+username))out.username=true;
                }
                return out;
            }''',username)
            if auth.get('success_selector'):
                info['configured']=bool(await visible(frame.locator(auth['success_selector'])))
            if urlparse(frame.url).hostname in {'betsson.it','www.betsson.it'}:
                info['site_member']=await frame.evaluate('''()=>!!document.querySelector('body.cg-body-logged #cg_user_wallet_logged')&&!!document.querySelector('body.cg-body-logged #cg-profile-popup-toggle')''')
            signals.append(info)
        except Exception:continue
    if not signals:return None
    flag=lambda name:any(s.get(name) for s in signals)
    if flag('password') or flag('otp'):return None
    if flag('configured'):return 'configured_marker'
    if flag('site_member'):return 'site_account_markers'
    if flag('logout'):return 'logout_control'
    if not flag('login'):
        if flag('username'):return 'account_identity'
        if flag('member') and flag('balance'):return 'account_and_balance'
    return None


def allowed_origin(initial,current):
    a,b=urlparse(initial),urlparse(current)
    if b.scheme not in {'http','https'} or not b.hostname or b.username or b.password:
        return False
    if b.scheme!=a.scheme and not (a.scheme=='http' and b.scheme=='https'):
        return False
    # Normal www canonicalization and HTTP->HTTPS are local-site redirects.
    host=lambda p:p.hostname.lower().removeprefix('www.')
    if host(a)!=host(b): return False
    if (a.port or (443 if a.scheme=='https' else 80))==(b.port or (443 if b.scheme=='https' else 80)):
        return True
    return a.port is None and b.port is None


async def visible(locator,limit=60):
    items=[]
    if await locator.count()>limit: raise LoginDiscoveryError('too_many_candidates')
    for i in range(await locator.count()):
        item=locator.nth(i)
        if await item.is_visible(): items.append(item)
    return items


async def unique(locator,required=False):
    items=await visible(locator)
    if len(items)>1: raise LoginDiscoveryError('ambiguous_login')
    if not items and required: raise LoginDiscoveryError('login_form_not_found')
    return items[0] if items else None


async def discover(page,auth,login_url):
    forms=[]
    for frame in page.frames:
        if not allowed_origin(login_url,frame.url): continue
        selector=auth.get('password_selector') or 'input[type="password"]'
        for password in await visible(frame.locator(selector)):
            if not await password.is_enabled(): continue
            # A registration form with password confirmation is not a login.
            scope=password.locator('xpath=ancestor::*[self::form or @role="dialog"][1]')
            if await scope.count()!=1: scope=frame.locator('body')
            if len(await visible(scope.locator('input[type="password"]')))!=1: continue
            signup=re.compile(r'^\s*(create\s+(an?\s+)?account|sign\s*up|register|зарегистрироваться|регистрация|зареєструватися|реєстрація)\s*$',re.I)
            if await visible(scope.get_by_role('button',name=signup)):
                continue
            meta=await password.evaluate('e=>({autocomplete:e.autocomplete,text:(e.closest("form")||e.closest("[role=dialog]")||e.parentElement).innerText})')
            if meta['autocomplete']=='new-password': continue
            if re.search(r'create account|sign up|register|регистрац|реєстрац',meta['text'],re.I) and not re.search(r'log.?in|sign.?in|войти|вход|увійти',meta['text'],re.I):
                continue
            forms.append((scope,password,frame))
    if len(forms)>1: raise LoginDiscoveryError('ambiguous_login')
    return forms[0] if forms else None


async def find_user(scope,auth):
    manual=auth.get('username_selector')
    if manual:
        user=await unique(scope.locator(manual))
        if user: return user
    candidates=await visible(scope.locator('input:not([type=hidden]):not([type=password]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button])'))
    ranked=[]
    for item in candidates:
        if not await item.is_enabled() or not await item.is_editable(): continue
        info=await item.evaluate('e=>({type:e.type,auto:e.autocomplete,text:[e.name,e.id,e.placeholder,e.getAttribute("aria-label"),...Array.from(e.labels||[],l=>l.innerText)].join(" ")})')
        score=100 if info['auto'] in {'username','email'} else 80 if info['type']=='email' else 60 if re.search(r'user|login|email|e-mail|логин|логін|почт|пошт|телефон|phone|nome utente|utente|indirizzo email|posta elettronica|telefono',info['text'],re.I) else 10 if info['type'] in {'text','tel'} else 0
        if score: ranked.append((score,item))
    ranked.sort(key=lambda pair:pair[0],reverse=True)
    if not ranked: raise LoginDiscoveryError('login_form_not_found')
    if len(ranked)>1 and ranked[0][0]==ranked[1][0]: raise LoginDiscoveryError('ambiguous_login')
    return ranked[0][1]


async def find_opener(page,login_url):
    candidates=[]
    for frame in page.frames:
        if not allowed_origin(login_url,frame.url):continue
        import secrets
        nonce=secrets.token_hex(8)
        metadata=await frame.evaluate('''nonce=>Array.from(document.querySelectorAll('button,a[href],[role="button"],input[type="button"],input[type="submit"],[tabindex]')).slice(0,250).flatMap((e,i)=>{
            const r=e.getBoundingClientRect(),s=getComputedStyle(e);if(!r.width||!r.height||s.visibility==='hidden'||s.display==='none'||e.disabled)return [];
            const key=nonce+'-'+i;e.setAttribute('data-qa-login',key);
            return [{key,names:[e.getAttribute('aria-label'),e.getAttribute('title'),e.innerText,e.value].filter(Boolean),href:e.getAttribute('href')||'',id:e.id,classes:typeof e.className==='string'?e.className:''}];})''',nonce)
        for meta in metadata:
            score=100 if any(LOGIN.fullmatch(n.strip()) for n in meta['names']) else 60 if re.search(r'(^|[/_?#-])(login|sign-in|signin|accesso|accedi)([/_?#-]|$)',meta['href'],re.I) else 40 if re.search(r'(^|[ _-])(login|signin)([ _-]|$)',meta['id']+' '+meta['classes'],re.I) else 0
            if score and not re.search(r'register|signup|регистрац', ' '.join(meta['names'])+' '+meta['href'],re.I):
                candidates.append((score,frame.locator('[data-qa-login="'+meta['key']+'"]')))
    if not candidates:return None
    candidates.sort(key=lambda pair:pair[0],reverse=True)
    # Equivalent desktop/mobile links are safe only when their targets agree.
    best=[node for score,node in candidates if score==candidates[0][0]]
    if len(best)>1:
        hrefs=[await node.get_attribute('href') for node in best]
        if not hrefs[0] or len(set(hrefs))!=1:raise LoginDiscoveryError('ambiguous_login')
    return best[0]


async def authenticate(page,auth,*,login_url,username,password,notify=lambda _:None,vision_request=None,session_state=None):
    state=session_state if session_state is not None else {}
    async def confirmed():
        evidence=await authenticated(page,auth,login_url,username)
        if evidence:
            state['confirmed']=True
            notify('Вход подтверждён. Ознака: '+evidence+'. Перехожу до пошуку гри.')
            return True
        return False
    mode=auth.get('mode','auto')
    if mode not in {'auto','manual'}: raise LoginDiscoveryError('invalid_login_mode')
    if not auth.get('_resume') and not state.get('submitted'):
        try:
            response=await page.goto(login_url,wait_until='domcontentloaded')
        except Exception as exc:
            # Report only Chromium's bounded error code, never a URL, proxy
            # credential, or the full Playwright exception containing secrets.
            match=re.search(r'\b(?:net::)?(ERR_[A-Z0-9_]+)\b',str(exc))
            if match:raise LoginDiscoveryError('navigation_'+match[1]) from exc
            if type(exc).__name__=='TimeoutError':
                raise LoginDiscoveryError('navigation_timeout') from exc
            raise
        if response and response.status==403:raise LoginDiscoveryError('login_access_denied')
        if response and response.status==429:raise LoginDiscoveryError('login_rate_limited')
    def check():
        if not allowed_origin(login_url,page.url): raise LoginOriginError('Unexpected login redirect')
    check()
    if await confirmed():return
    if state.get('submitted'):
        # A resume must not submit a second login or reopen a dismissed modal.
        raise LoginDiscoveryError('login_not_confirmed')
    if mode=='manual':
        user=await unique(page.locator(auth['username_selector']),required=True)
        secret=await unique(page.locator(auth['password_selector']),required=True)
        submit=await unique(page.locator(auth['submit_selector']),required=True)
        frame=page.main_frame
    else:
        notify('Ищу форму входа на странице…')
        form=None
        # Give client-rendered forms a bounded chance to mount first.
        for _ in range(8):
            if await confirmed():return
            check(); form=await discover(page,auth,login_url)
            if form: break
            await asyncio.sleep(.2)
        if not form:
            opener=None
            if auth.get('open_selector'):
                opener=await unique(page.locator(auth['open_selector']),required=True)
            else:
                for _ in range(20):
                    check();opener=await find_opener(page,login_url)
                    if opener:break
                    form=await discover(page,auth,login_url)
                    if form:break
                    if auth.get('vision'):break
                    await asyncio.sleep(.3)
                if not opener and not form and auth.get('vision'):
                    from room_agent import RoomAgent,AgentError
                    agent=RoomAgent(page,vision_request or page.context.request,auth['vision'],notify=notify)
                    try:
                        for step in range(4):
                            if await confirmed():return
                            items=await agent.observe()
                            # Authentication must never wander into game categories.
                            # Only same-origin sign-in, consent and menu controls can
                            # expose the form. Credentials remain outside the model.
                            items=[i for i in items if i['kind']=='click'
                                and (not i.get('href') or allowed_origin(login_url,i['href']))
                                and not re.search(r'casino|casinò|sport|poker|registr|sign.?up',i['label'],re.I)
                                and re.search(r'acced|accesso|entra|login|sign.?in|вход|войти|увійти|menu|menù|account|profil|accett|consent|cookie|rifiut|reject|accept',i['label'],re.I)]
                            if not items:
                                raise AgentError('Не знайдено доступної кнопки входу, меню або cookies. ІІ не переходить у розділи ігор під час входу.')
                            command=await agent.model_choice(items,'open the sign-in form on this page; do not navigate to games yet')
                            if command.get('action') not in {'click','wait'}:raise AgentError('Модель не визначила кнопку входу.')
                            await agent.act(items,command)
                            for _ in range(10):
                                if await confirmed():return
                                check();form=await discover(agent.page,auth,login_url)
                                if form:break
                                await asyncio.sleep(.2)
                            if form:break
                        if agent.page is not page:raise LoginDiscoveryError('login_popup_requires_review')
                    except AgentError as exc:
                        notify(str(exc));raise LoginDiscoveryError('vision_login_unavailable') from exc
            if form:
                opener=None
            elif not opener: raise LoginDiscoveryError('login_button_not_found')
            if opener:
                notify('Найдена кнопка входа. Открываю форму…')
                await opener.click(timeout=5000)
            for _ in range(40):
                check(); form=await discover(page,auth,login_url)
                if form: break
                await asyncio.sleep(.2)
        if not form: raise LoginDiscoveryError('login_form_not_found')
        scope,secret,frame=form
        user=await find_user(scope,auth)
        submit=None
        if auth.get('submit_selector'):
            submit=await unique(scope.locator(auth['submit_selector']))
        if submit is None:
            submit=await unique(scope.get_by_role('button',name=LOGIN))
        if submit is None:
            submit=await unique(scope.locator('button[type="submit"],input[type="submit"]'),required=True)
    check()
    if not allowed_origin(login_url,frame.url): raise LoginOriginError('Login frame changed origin')
    notify('Форма найдена. Ввожу данные аккаунта…')
    await user.fill(username)
    check()
    if not allowed_origin(login_url,frame.url): raise LoginOriginError('Login frame changed origin')
    await secret.fill(password)
    check()
    if not allowed_origin(login_url,frame.url): raise LoginOriginError('Login frame changed origin')
    state['submitted']=True
    await submit.click(timeout=5000)
    notify('Данные отправлены. Проверяю успешный вход…')
    for _ in range(120):
        check()
        if await visible(page.locator('input[autocomplete="one-time-code"]')):
            raise LoginDiscoveryError('login_requires_verification')
        if await confirmed():return
        await asyncio.sleep(.2)
    raise LoginDiscoveryError('login_not_confirmed')
