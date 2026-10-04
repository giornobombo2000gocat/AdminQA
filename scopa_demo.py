"""Independent local training tables; transitions use the original rules."""
import copy
import json
from pathlib import Path
from fastapi import HTTPException, Body
from fastapi.responses import HTMLResponse
from backend.app.schemas.games import GameStateSchema
from backend.app.services.serialization import state_from_schema, state_to_wire
from engine.cards import Deck
from engine.game_state import GameState, CapturedCards, Player
from engine.rules import RulesEngine


def scenario(name):
    deck=Deck.create(); cards={c.id:c for c in deck.cards}
    if name=='risk':
        own=tuple(cards[c] for c in ('coppe:4','coppe:6'))
        table=tuple(cards[c] for c in ('denari:2','denari:3'))
        active=own+table+tuple(cards[c] for c in ('spade:9','bastoni:10'))
        state=GameState(player_hand=own,table_cards=table,opponent_hand_size=1,
            captured_cards=CapturedCards(tuple(c for c in deck.cards if c not in active),()),
            last_capture_player=Player.PLAYER)
        return state,2,'Смотрим на ход вперёд: движок выберет 6 чаш, хотя первой в руке стоит 4.'
    state=GameState(player_hand=(cards['coppe:8'],),opponent_hand_size=1,
        table_cards=tuple(cards[c] for c in ('denari:7','coppe:1','spade:2','bastoni:3','spade:5')))
    return state,1,'Три способа набрать 8. Движок забирает 7 монет (Sette bello) вместе с 1 чаш.'


def mount_demo(app, html_path):
    tables={}
    def get(sid):
        if not 1<=len(sid)<=100: raise HTTPException(422,'Invalid demo session')
        if sid not in tables:
            if len(tables)>=100: raise HTTPException(503,'Demo table limit')
            reset(sid,'sette')
        return tables[sid]
    def reset(sid,name):
        if name not in {'sette','risk'}: raise HTTPException(422,'Unknown scenario')
        state,depth,hint=scenario(name)
        revision=tables.get(sid,{}).get('revision',0)+1
        tables[sid]={'state':state_to_wire(state),'revision':revision,
                     'search':{'max_depth':depth},'hint':hint,'scenario':name,'result':None}
        return tables[sid]
    @app.get('/demo',response_class=HTMLResponse)
    async def demo(): return Path(html_path).read_text(encoding='utf-8')
    @app.get('/demo/state')
    async def state(sid:str='manual'): return copy.deepcopy(get(sid))
    @app.post('/demo/reset')
    async def reset_route(payload:dict=Body(...)):
        sid=payload.get('sid','manual'); get(sid)
        return copy.deepcopy(reset(sid,payload.get('scenario','sette')))
    @app.post('/demo/commit')
    async def commit(payload:dict=Body(...)):
        item=get(payload.get('sid','manual'))
        if payload.get('revision')!=item['revision']: raise HTTPException(409,'Stale state')
        state=state_from_schema(GameStateSchema.model_validate(item['state']))
        if state.current_player!=Player.PLAYER: raise HTTPException(409,'Not player turn')
        captures=payload.get('captured_cards',[])
        if not isinstance(captures,list) or len(captures)!=len(set(captures)):
            raise HTTPException(422,'Invalid capture list')
        matching=[m for m in RulesEngine().get_legal_moves(state)
            if m.played_card.id==payload.get('played_card') and
            {c.id for c in m.captured_cards}==set(captures)]
        if len(matching)!=1: raise HTTPException(422,'Illegal capture combination')
        before=copy.deepcopy(item['state'])
        item['state']=state_to_wire(matching[0].resulting_state)
        item['revision']+=1
        item['result']={'played_card':matching[0].played_card.id,'captured_cards':captures,
                        'before':before,'after':copy.deepcopy(item['state'])}
        return copy.deepcopy(item)
    return tables
