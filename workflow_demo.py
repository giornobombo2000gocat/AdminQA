"""Local virtual-chip fixture for the complete account->table->engine flow."""
import json
import re
import secrets
from pathlib import Path
from fastapi import Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

USER='qa@local.test'
PASSWORD='qa-demo'
STYLE='<meta charset="utf-8"><style>body{font:20px Segoe UI;margin:40px;background:#eef2f8;color:#182740}button,a,input{font:inherit;padding:12px;margin:8px}a{display:inline-block;background:white;border-radius:8px}label{display:block}form{background:white;padding:24px;max-width:520px;border-radius:14px}</style>'

def mount_workflow(app,html_path):
    worlds={}
    def world(sid):
        if not isinstance(sid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',sid):raise HTTPException(422,'Invalid session')
        if sid not in worlds:
            if len(worlds)>=100:raise HTTPException(503,'Demo session limit')
            worlds[sid]={'token':secrets.token_hex(16),'events':[],'seated':False,'chips':0,'bet':None}
        return worlds[sid]
    def require(req,sid):
        w=world(sid)
        if req.cookies.get('qa_workflow')!=w['token']:raise HTTPException(401,'Login required')
        return w
    def logged_header(sid):return '<button>Выйти</button><p>Только виртуальные фишки. Игра Scopa, комната Учебная, стол 5.</p>'
    @app.get('/workflow/login',response_class=HTMLResponse)
    async def login_page(sid:str='workflow'):
        world(sid)
        return STYLE+'''<h1>Демо полного автоматического цикла</h1><button id="open">Войти</button>
<div role="dialog" hidden><form id="login"><h2>Вход</h2><label>Логин<input type="email" name="username" autocomplete="username"></label><label>Пароль<input type="password" autocomplete="current-password"></label><button type="submit">Войти</button><p id="error"></p></form></div>
<script>document.querySelector('#open').onclick=()=>document.querySelector('[role=dialog]').hidden=false;
document.querySelector('#login').onsubmit=async e=>{e.preventDefault();let r=await fetch('/workflow/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid:'''+json.dumps(sid)+''',username:document.querySelector('input[type=email]').value,password:document.querySelector('input[type=password]').value})});if(r.ok)location.href='''+json.dumps('/workflow/lobby?sid='+sid)+''';else document.querySelector('#error').textContent='Неверные данные';};</script>'''
    @app.post('/workflow/auth')
    async def auth(data:dict=Body(...)):
        sid=data.get('sid','workflow');w=world(sid)
        if data.get('username')!=USER or data.get('password')!=PASSWORD:raise HTTPException(401,'Invalid credentials')
        w['events'].append('authenticated')
        response=JSONResponse({'ok':True});response.set_cookie('qa_workflow',w['token'],httponly=True,samesite='strict')
        return response
    @app.get('/workflow/lobby',response_class=HTMLResponse)
    async def lobby(req:Request,sid:str):
        require(req,sid)
        return STYLE+logged_header(sid)+'<h1>Лобби</h1><a href="/workflow/games?sid='+sid+'">Игры</a><button>Пополнить</button><button>Вывод</button>'
    @app.get('/workflow/games',response_class=HTMLResponse)
    async def games(req:Request,sid:str):
        w=require(req,sid);w['events'].append('games')
        return STYLE+logged_header(sid)+'<h1>Игры</h1><a href="/workflow/rooms?sid='+sid+'">Scopa</a><button disabled>Другая игра</button>'
    @app.get('/workflow/rooms',response_class=HTMLResponse)
    async def rooms(req:Request,sid:str):
        w=require(req,sid);w['events'].append('game:Scopa')
        return STYLE+logged_header(sid)+'<h1>Комнаты Scopa</h1><a href="/workflow/tables?sid='+sid+'">Учебная</a><button disabled>Опытные игроки — нет мест</button>'
    @app.get('/workflow/tables',response_class=HTMLResponse)
    async def tables(req:Request,sid:str):
        w=require(req,sid);w['events'].append('room:Учебная')
        return STYLE+logged_header(sid)+'<h1>Столы</h1><button disabled>Стол 15 — занят</button><a href="/workflow/table?sid='+sid+'">Стол 5</a>'
    @app.get('/workflow/table',response_class=HTMLResponse)
    async def table(req:Request,sid:str):
        w=require(req,sid);w['events'].append('table:5')
        return STYLE+logged_header(sid)+'''<h1>Стол 5</h1><label>Виртуальные фишки<input type="number" id="chips" aria-label="Виртуальные фишки" min="1" max="100"></label><button id="sit">Сесть</button><p id="error"></p>
<script>document.querySelector('#sit').onclick=async()=>{let r=await fetch('/workflow/seat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid:'''+json.dumps(sid)+''',chips:Number(document.querySelector('#chips').value)})});if(r.ok)location.href='''+json.dumps('/workflow/play?sid='+sid)+''';else document.querySelector('#error').textContent='Некорректные фишки';};</script>'''
    @app.post('/workflow/seat')
    async def seat(req:Request,data:dict=Body(...)):
        w=require(req,data.get('sid'))
        chips=data.get('chips')
        if type(chips) is not int or not 1<=chips<=100:raise HTTPException(422,'Invalid chips')
        if w['seated']:raise HTTPException(409,'Already seated')
        w['seated']=True;w['chips']=chips;w['events'].append('seated')
        return {'ok':True}
    @app.post('/workflow/bet')
    async def bet(req:Request,data:dict=Body(...)):
        w=require(req,data.get('sid'));chips=data.get('chips')
        if not w['seated'] or type(chips) is not int or not 1<=chips<=w['chips']:raise HTTPException(422,'Invalid bet')
        if w['bet'] is not None:raise HTTPException(409,'Bet already submitted')
        w['bet']=chips;w['events'].append('bet')
        return {'ok':True}
    @app.get('/workflow/play',response_class=HTMLResponse)
    async def play(req:Request,sid:str):
        w=require(req,sid)
        if not w['seated']:raise HTTPException(409,'Not seated')
        html=Path(html_path).read_text(encoding='utf-8')
        old='JSON.stringify({revision:m.revision,state:m.state,search:m.search})'
        new="JSON.stringify({revision:m.revision,state:m.state,search:m.search,seated:true,bet_required:window.qaBetRequired,room:{game:'Scopa',room:'Учебная',table:'5'}})"
        if html.count(old)!=1:raise RuntimeError('Demo state bridge changed')
        html=html.replace(old,new)
        controls='''<section id="qa-bet"><h2>Виртуальная ставка перед ходом</h2><label>Ставка фишек<input type="number" id="bet-chips" aria-label="Ставка фишек" min="1" max="100"></label><button id="bet-submit">Сделать ставку</button><span id="bet-result"></span></section>'''
        setup='''<script>window.qaBetRequired=true;document.querySelector('#bet-submit').onclick=async()=>{let r=await fetch('/workflow/bet',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid:'''+json.dumps(sid)+''',chips:Number(document.querySelector('#bet-chips').value)})});if(r.ok){window.qaBetRequired=false;let node=document.querySelector('#game-state'),data=JSON.parse(node.textContent);data.bet_required=false;node.textContent=JSON.stringify(data);document.querySelector('#qa-bet').hidden=true;document.querySelector('#bet-result').textContent='Ставка принята';}};</script>'''
        return html.replace('<main>','<main>'+controls+setup,1)
    return worlds
