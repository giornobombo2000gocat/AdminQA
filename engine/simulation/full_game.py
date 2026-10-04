"""Complete offline 40-card rounds, with private opponent information."""
from dataclasses import dataclass
from random import Random

from engine.cards import Deck
from engine.game_state import GameState, Player
from engine.rules import RulesEngine
from engine.scoring import ScoringEngine
from engine.decision_engine import DecisionConfig, DecisionEngine
from engine.game_tree import SearchConfig
from engine.probabilities import ProbabilityConfig
from .rollout import iteration_seed, player_action


@dataclass(frozen=True)
class RoundResult:
    index: int
    seed: int
    starter: str
    player_points: int
    opponent_points: int
    player_scopa: int
    opponent_scopa: int
    turns: int
    captured_cards: int

    @property
    def outcome(self) -> str:
        return "win" if self.player_points > self.opponent_points else "loss" if self.player_points < self.opponent_points else "draw"


def play_round(index: int, seed: int = 20261001, *, verify_decisions: bool = False) -> RoundResult:
    """Depth-one DecisionEngine versus uniform legal opponent; alternating starter.

    Initial four table cards accept all shuffled deals. One game means one
    complete round, not a multi-round match to a target score.
    """
    derived_seed = iteration_seed(seed, index)
    rng = Random(derived_seed)
    universe = Deck.create()
    cards = list(universe.cards)
    rng.shuffle(cards)
    starter = Player.PLAYER if index % 2 == 0 else Player.OPPONENT
    table, draw = tuple(cards[:4]), cards[4:]
    state = GameState(deck=universe, table_cards=table, current_player=starter,
                      draw_pile_size=len(draw))
    opponent_hand = ()
    rules, scoring = RulesEngine(), ScoringEngine()
    decision = DecisionEngine(DecisionConfig(
        search=SearchConfig(max_depth=1, first_player=starter, probability_method="monte_carlo"),
        probabilities=ProbabilityConfig(monte_carlo_samples=1, seed=derived_seed)))
    while draw or state.player_hand or opponent_hand:
        if not state.player_hand and not opponent_hand:
            first, second = tuple(draw[:3]), tuple(draw[3:6])
            del draw[:6]
            own, opponent_hand = (first, second) if starter == Player.PLAYER else (second, first)
            state = state.evolve(player_hand=own, opponent_hand_size=len(opponent_hand),
                                 draw_pile_size=len(draw), current_player=starter)
        if state.current_player == Player.PLAYER:
            move = player_action(rules.get_legal_moves(state), decision.tree.evaluator, "greedy")
            # A depth-one cutoff that triggers redealing has identical utility:
            # PositionEvaluator depends only on captures, not newly dealt hands.
            # Avoid enumerating all permutations of that otherwise irrelevant deal.
            if verify_decisions and not (len(state.player_hand) == 1 and state.opponent_hand_size == 0 and state.draw_pile_size):
                reference = decision.analyze(state).recommended_move
                if (move.played_card, move.captured_cards) != (reference.played_card, reference.captured_cards):
                    raise RuntimeError("Depth-one policy disagrees with DecisionEngine")
            if move is None:
                raise RuntimeError("Decision engine returned no move")
            state = move.resulting_state
        else:
            visible = state.evolve(opponent_known_cards=opponent_hand)
            legal = rules.get_legal_moves(visible)
            move = legal[rng.randrange(len(legal))]
            state = rules.apply_move(state, move)
            opponent_hand = tuple(c for c in opponent_hand if c != move.played_card)
        if state.opponent_known_cards:
            raise RuntimeError("Private opponent cards leaked")
    points = scoring.calculate_score(state).round_points
    captured = len(state.captured_cards.player) + len(state.captured_cards.opponent)
    if state.turn_number != 36 or captured != 40:
        raise RuntimeError("Incomplete round")
    return RoundResult(index, derived_seed, starter.value, points.player, points.opponent,
                       state.scopa_count.player, state.scopa_count.opponent, state.turn_number, captured)


def play_batch(indices: tuple[int, ...], seed: int) -> tuple[RoundResult, ...]:
    return tuple(play_round(i, seed) for i in indices)
