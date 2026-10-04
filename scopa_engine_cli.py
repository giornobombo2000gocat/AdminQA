"""JSON stdin/stdout wrapper for the original Scopa DecisionEngine.

This wrapper does not infer a game state from a generic DOM card list.
"""
from __future__ import annotations
import argparse
import json
import sys

from backend.app.schemas.games import GameStateSchema
from backend.app.services.serialization import state_from_schema, state_to_wire
from engine.cards import Deck
from engine.decision_engine import DecisionConfig, DecisionEngine
from engine.game_state import CapturedCards, GameState, Player
from engine.game_tree import SearchConfig


def move_key(move):
    return move.played_card.id, tuple(sorted(card.id for card in move.captured_cards))


def candidate_key(item):
    if not isinstance(item,dict) or not isinstance(item.get('played_card'),str):
        raise ValueError('Each legal_moves entry must contain played_card and captured_cards')
    captures=item.get('captured_cards')
    if not isinstance(captures,list) or any(not isinstance(c,str) for c in captures):
        raise ValueError('captured_cards must be an array of canonical card IDs')
    if len(captures)!=len(set(captures)):
        raise ValueError('Duplicate capture card')
    return item['played_card'],tuple(sorted(captures))


def analyze(payload):
    if not isinstance(payload,dict):
        raise ValueError('Input must be a JSON object')
    state_data=payload.get('state',payload)
    if not isinstance(state_data,dict) or not {'player_hand','table_cards'} <= state_data.keys():
        raise ValueError('Full game state required: player_hand and table_cards; a DOM cards list is insufficient')
    if state_data is payload:
        state_data={k:v for k,v in payload.items() if k not in {'search','legal_moves'}}
    state=state_from_schema(GameStateSchema.model_validate(state_data))
    options=payload.get('search',{})
    if not isinstance(options,dict): raise ValueError('search must be an object')
    search=SearchConfig(**options)
    if search.max_depth>12 or search.max_nodes>100_000 or search.max_belief_worlds>100_000:
        raise ValueError('Search limits exceed supported bounds')
    result=DecisionEngine(DecisionConfig(search=search)).analyze(state)
    if result.recommended_move is None:
        raise ValueError(f'No recommended move: {result.status}')
    legal_keys=[move_key(item.move) for item in result.all_moves]
    supplied=payload.get('legal_moves')
    if supplied is not None:
        if not isinstance(supplied,list) or not supplied:
            raise ValueError('legal_moves must be a nonempty array')
        ordered=[candidate_key(item) for item in supplied]
        if len(set(ordered))!=len(ordered) or set(ordered)!=set(legal_keys):
            raise ValueError('legal_moves must contain every legal action exactly once')
    else:
        ordered=legal_keys
    best=result.recommended_move
    return {'move_index':ordered.index(move_key(best)),
            'played_card':best.played_card.id,
            'captured_cards':[card.id for card in best.captured_cards],
            'source':'Scopa DecisionEngine', 'search_depth':result.search_depth,
            'calculation_ms':round(result.calculation_time*1000,2),
            'alternatives':[{'played_card':a.move.played_card.id,
                'captured_cards':[c.id for c in a.move.captured_cards],
                'expected_value':float(a.expected_value),
                'expected_value_exact':str(a.expected_value),
                'scopa_probability':float(a.scopa_probability)} for a in result.all_moves]}


def self_test():
    deck=Deck.create(); cards={card.id:card for card in deck.cards}
    sette=GameState(player_hand=(cards['coppe:8'],),opponent_hand_size=1,
        table_cards=tuple(cards[key] for key in ('denari:7','coppe:1','spade:2','bastoni:3','spade:5')))
    own=(cards['coppe:4'],cards['coppe:6'])
    table=(cards['denari:2'],cards['denari:3'])
    hidden=(cards['spade:9'],cards['bastoni:10'])
    active=own+table+hidden
    risk=GameState(player_hand=own,table_cards=table,opponent_hand_size=1,
        captured_cards=CapturedCards(tuple(c for c in deck.cards if c not in active),()),
        last_capture_player=Player.PLAYER)
    first=analyze({'state':state_to_wire(sette),'search':{'max_depth':1}})
    assert 'denari:7' in first['captured_cards'] and len(first['captured_cards'])==2
    assert analyze({'state':state_to_wire(risk),'search':{'max_depth':1}})['played_card']=='coppe:4'
    assert analyze({'state':state_to_wire(risk),'search':{'max_depth':2}})['played_card']=='coppe:6'
    try:
        analyze({'cards':[{'value':'7','suit':'hearts'}]})
    except ValueError: pass
    else: raise AssertionError('Incomplete DOM data must be rejected')
    return {'status':'ok','checks':['sette_bello','risk_depth1','risk_depth2','incomplete_state_rejected']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--input',help='Optional JSON input file; default: stdin')
    args=parser.parse_args()
    try:
        if args.self_test:
            result=self_test()
        else:
            if args.input:
                with open(args.input,encoding='utf-8') as source: payload=json.load(source)
            else:
                raw=sys.stdin.buffer.read(1_048_577)
                if len(raw)>1_048_576: raise ValueError('Input exceeds 1 MiB')
                payload=json.loads(raw.decode('utf-8-sig'))
            result=analyze(payload)
        sys.stdout.write(json.dumps(result,ensure_ascii=True)+'\n')
        return 0
    except Exception as exc:
        sys.stderr.write(f'{type(exc).__name__}: {exc}\n')
        return 2


if __name__=='__main__':
    raise SystemExit(main())
