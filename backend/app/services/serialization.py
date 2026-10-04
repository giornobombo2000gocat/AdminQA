"""Transport adapters only: no rules, probability or evaluation calculations."""
from dataclasses import fields, is_dataclass
from enum import Enum
from fractions import Fraction

from engine.cards import Card, Deck
from engine.game_state import CapturedCards, GameState, HistoryEntry, PlayerCounts
from engine.game_tree import PositionEvaluation
from backend.app.schemas.games import GameResponse, GameStateSchema
from backend.app.schemas.results import AnalysisResponse, SimulationResponse


def state_from_schema(data: GameStateSchema) -> GameState:
    deck = Deck(tuple(Card(**c.model_dump()) for c in data.deck))
    cards = {c.id: c for c in deck.cards}
    def resolve(ids):
        try:
            return tuple(cards[key] for key in ids)
        except KeyError as error:
            raise ValueError(f'Unknown card id: {error.args[0]}') from None
    return GameState(deck=deck,
        table_cards=resolve(data.table_cards), player_hand=resolve(data.player_hand),
        opponent_known_cards=resolve(data.opponent_known_cards), played_cards=resolve(data.played_cards),
        captured_cards=CapturedCards(resolve(data.captured_cards.player), resolve(data.captured_cards.opponent)),
        current_player=data.current_player, turn_number=data.turn_number, round_number=data.round_number,
        player_score=data.player_score, opponent_score=data.opponent_score,
        scopa_count=PlayerCounts(**data.scopa_count.model_dump()), opponent_hand_size=data.opponent_hand_size,
        draw_pile_size=data.draw_pile_size, last_capture_player=data.last_capture_player,
        game_history=tuple(HistoryEntry(h.turn_number, h.actor, resolve([h.played_card])[0],
            resolve(h.captured_cards)) for h in data.game_history))


def state_to_wire(state):
    ids = lambda cards: [c.id for c in cards]
    return dict(deck=to_wire(state.deck.cards), table_cards=ids(state.table_cards),
        player_hand=ids(state.player_hand), opponent_known_cards=ids(state.opponent_known_cards),
        played_cards=ids(state.played_cards), captured_cards=dict(player=ids(state.captured_cards.player),
            opponent=ids(state.captured_cards.opponent)), current_player=state.current_player.value,
        turn_number=state.turn_number, round_number=state.round_number, player_score=state.player_score,
        opponent_score=state.opponent_score, scopa_count=to_wire(state.scopa_count),
        opponent_hand_size=state.opponent_hand_size, draw_pile_size=state.draw_pile_size,
        last_capture_player=state.last_capture_player.value if state.last_capture_player else None,
        game_history=[dict(turn_number=h.turn_number, actor=h.actor.value, played_card=h.played_card.id,
            captured_cards=ids(h.captured_cards)) for h in state.game_history])


def to_wire(value):
    if isinstance(value, Fraction):
        return dict(numerator=value.numerator, denominator=value.denominator)
    if isinstance(value, GameState):
        return state_to_wire(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        result = {f.name: to_wire(getattr(value, f.name)) for f in fields(value)}
        if isinstance(value, PositionEvaluation):
            result['total'] = to_wire(value.total)
        return result
    if isinstance(value, (tuple, list)):
        return [to_wire(item) for item in value]
    return value


def game_response(record):
    return GameResponse(id=record.id, revision=record.revision,
        state=state_to_wire(record.state), has_analysis=record.analysis is not None,
        has_simulation=record.simulation is not None)


def analysis_response(record):
    result = record.analysis
    belief = result.probabilities
    summary = None if belief is None else dict(method=belief.method, exact=belief.exact,
        seed=belief.seed, sample_count=belief.sample_count, world_count=belief.state.world_count,
        known_cards=[c.id for c in belief.state.known_cards], unknown_cards=[c.id for c in belief.state.unknown_cards])
    return AnalysisResponse(game_id=record.id, state_revision=record.revision, status=result.status,
        all_moves=to_wire(result.all_moves), recommended_move=to_wire(result.recommended_move),
        expected_value=to_wire(result.expected_value), scopa_probability=to_wire(result.scopa_probability),
        primiera_value=to_wire(result.primiera_value), sette_bello_value=to_wire(result.sette_bello_value),
        opponent_expected_value=to_wire(result.opponent_expected_value), probabilities=summary,
        search_depth=result.search_depth, reached_depth=result.reached_depth,
        explored_states=result.tree.node_count if result.tree else 0, calculation_time_seconds=result.calculation_time)


def simulation_response(record):
    data = to_wire(record.simulation)
    data['calculation_time_seconds'] = data.pop('calculation_time')
    return SimulationResponse(game_id=record.id, state_revision=record.revision, **data)
