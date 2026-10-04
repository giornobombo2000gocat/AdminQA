"""Offline three- and four-player individual Scopa, individual scores and public depth-one policy."""
from dataclasses import dataclass, replace
from fractions import Fraction
from random import Random

from engine.cards import Card, Deck, validate_unique
from engine.rules import RulesEngine, IllegalMove
from engine.scoring.config import ScoringConfig
from engine.scoring.primiera import calculate_primiera
from engine.game_tree import EvaluationConfig
from .rollout import iteration_seed


@dataclass(frozen=True)
class MultiplayerState:
    table: tuple[Card, ...]
    hands: tuple[tuple[Card, ...], ...]
    captures: tuple[tuple[Card, ...], ...] = ((), (), ())
    scopa: tuple[int, ...] = (0, 0, 0)
    turn: int = 0
    draw: tuple[Card, ...] = ()
    last_capture: int | None = None
    played: int = 0

    def __post_init__(self):
        if len(self.hands) not in (3, 4) or len(self.captures) != len(self.hands) or len(self.scopa) != len(self.hands):
            raise ValueError("Three or four equally represented players required")
        if self.turn not in range(len(self.hands)) or any(n < 0 for n in self.scopa):
            raise ValueError("Invalid turn or scopa")
        validate_unique(self.table + self.draw + sum(self.hands, ()) + sum(self.captures, ()))


@dataclass(frozen=True)
class MultiplayerMove:
    card: Card
    capture: tuple[Card, ...] = ()


def move_key(move):
    return move.card.id, tuple(sorted(c.id for c in move.capture))


def legal_moves(state: MultiplayerState) -> tuple[MultiplayerMove, ...]:
    rules = RulesEngine()
    return tuple(MultiplayerMove(card, capture) for card in sorted(state.hands[state.turn], key=lambda c: c.id)
                 for capture in (rules.get_captures(card, state.table) or ((),)))


def apply_move(state: MultiplayerState, move: MultiplayerMove) -> MultiplayerState:
    if move not in legal_moves(state):
        raise IllegalMove("Invalid three-player move")
    actor = state.turn
    hands = list(state.hands)
    hands[actor] = tuple(c for c in hands[actor] if c != move.card)
    table = tuple(c for c in state.table if c not in move.capture) if move.capture else state.table + (move.card,)
    captures, scopa = list(state.captures), list(state.scopa)
    last = state.last_capture
    final = not state.draw and not any(hands)
    if move.capture:
        captures[actor] += (move.card,) + move.capture
        last = actor
        scopa[actor] += int(not table and not final)
    if final and table:
        if last is None:
            raise ValueError("Final leftovers require last capture owner")
        captures[last] += table
        table = ()
    return MultiplayerState(table, tuple(hands), tuple(captures), tuple(scopa),
                      (actor + 1) % len(hands), state.draw, last, state.played + 1)


def category_values(captures, config):
    prime = tuple(calculate_primiera(pile, config) for pile in captures)
    return (tuple(len(pile) for pile in captures),
            tuple(sum(c.suit == config.denari_suit for c in pile) for pile in captures),
            tuple(int(any(c.suit == config.denari_suit and c.rank == config.sette_bello_rank for c in pile)) for pile in captures),
            tuple(p.value if p.eligible else -1 for p in prime))


def final_points(state: MultiplayerState, config: ScoringConfig | None = None) -> tuple[int, ...]:
    config = config or ScoringConfig()
    if state.table or state.draw or any(state.hands) or set(sum(state.captures, ())) != set(Deck.create(config.deck_config).cards):
        raise ValueError("Only settled complete rounds may be scored")
    points = [count * config.scopa_points for count in state.scopa]
    weights = (config.captured_cards_points, config.denari_points, config.sette_bello_points, config.primiera_points)
    for values, weight in zip(category_values(state.captures, config), weights):
        maximum = max(values)
        winners = [i for i in range(len(values)) if values[i] == maximum]
        if len(winners) == 1 and maximum >= 0:
            points[winners[0]] += weight
    return tuple(points)


def public_utility(table, captures, scopa, actor, config, weights, terminal=False):
    """Own utility minus strongest rival. Never receives opponents' hands/deck."""
    if terminal:
        state = MultiplayerState(table, ((),) * len(captures), captures, scopa)
        totals = tuple(Fraction(n) for n in final_points(state, config))
    else:
        prime = tuple(calculate_primiera(pile, config) for pile in captures)
        max_prime = len(config.deck_config.suits) * max(dict(config.primiera_values).values())
        denari_size = len(config.deck_config.ranks)
        totals = tuple(
            Fraction(len(pile), 40) * weights.captured_cards +
            Fraction(scopa[i] * config.scopa_points) * weights.scopa +
            Fraction(sum(c.suit == config.denari_suit for c in pile), denari_size) * weights.denari +
            Fraction(int(any(c.suit == config.denari_suit and c.rank == config.sette_bello_rank for c in pile)) * config.sette_bello_points) * weights.sette_bello +
            Fraction(prime[i].value, max_prime) * weights.primiera
            for i, pile in enumerate(captures))
    return totals[actor] - max(totals[i] for i in range(len(captures)) if i != actor)


def recommend(state: MultiplayerState) -> MultiplayerMove:
    config, weights = ScoringConfig(), EvaluationConfig()
    candidates = []
    for move in legal_moves(state):
        successor = apply_move(state, move)
        terminal = not successor.draw and not any(successor.hands)
        value = public_utility(successor.table, successor.captures, successor.scopa, state.turn, config, weights, terminal)
        candidates.append((value, move))
    if not candidates:
        raise IllegalMove("Acting hand empty")
    return min(candidates, key=lambda pair: (-pair[0], move_key(pair[1])))[1]


@dataclass(frozen=True)
class MultiplayerResult:
    index: int
    seed: int
    starter: int
    points: tuple[int, ...]
    scopa: tuple[int, ...]
    turns: int
    captured_cards: int

    @property
    def outcome(self):
        best = max(self.points)
        if self.points[0] < best:
            return "loss"
        return "win" if self.points.count(best) == 1 else "draw"


def play_round(index: int, seed: int = 20261001, players: int = 3) -> MultiplayerResult:
    if players not in (3, 4):
        raise ValueError("Expected three or four players")
    derived = iteration_seed(seed, index)
    rng = Random(derived)
    cards = list(Deck.create().cards)
    rng.shuffle(cards)
    starter = index % players
    state = MultiplayerState(tuple(cards[:4]), ((),) * players, captures=((),) * players, scopa=(0,) * players, turn=starter, draw=tuple(cards[4:]))
    while state.draw or any(state.hands):
        if not any(state.hands):
            hands = [()] * players
            for offset in range(players):
                hands[(starter + offset) % players] = state.draw[offset*3:offset*3+3]
            state = replace(state, hands=tuple(hands), draw=state.draw[3 * players:], turn=starter)
        moves = legal_moves(state)
        move = recommend(state) if state.turn == 0 else moves[rng.randrange(len(moves))]
        state = apply_move(state, move)
    points = final_points(state)
    total = sum(map(len, state.captures))
    if state.played != 36 or total != 40:
        raise RuntimeError("Incomplete three-player round")
    return MultiplayerResult(index, derived, starter, points, state.scopa, state.played, total)


def play_batch(indices, seed, players=3):
    return tuple(play_round(i, seed, players) for i in indices)
