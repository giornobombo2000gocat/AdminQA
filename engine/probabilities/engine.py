from collections.abc import Callable, Iterable
from fractions import Fraction
from math import comb

from engine.cards import Card, validate_unique
from engine.game_state import GameState
from .combinatorics import combinations_count, hypergeometric_pmf
from .config import ProbabilityConfig
from .exact import enumerate_worlds
from .models import ProbabilityDistribution, ProbabilityState, Region
from .monte_carlo import sample_worlds


class ProbabilityEngine:
    """Uniform prior conditional on known card identities and region sizes."""

    def __init__(self, config: ProbabilityConfig | None = None):
        self.config = config or ProbabilityConfig()

    @staticmethod
    def state(state: GameState | ProbabilityState) -> ProbabilityState:
        if isinstance(state, GameState):
            return ProbabilityState.from_game_state(state)
        if not isinstance(state, ProbabilityState):
            raise TypeError("Expected GameState or ProbabilityState")
        return state

    def distribution(self, state: GameState | ProbabilityState, method: str = "auto") -> ProbabilityDistribution:
        state = self.state(state)
        if method == "auto":
            method = "exact" if state.world_count <= self.config.max_exact_worlds else "monte_carlo"
        if method == "exact":
            return enumerate_worlds(state, self.config.max_exact_worlds)
        if method == "monte_carlo":
            return sample_worlds(state, self.config.monte_carlo_samples, self.config.seed)
        raise ValueError("Method must be auto, exact or monte_carlo")

    def card_probability(self, state: GameState | ProbabilityState, card: Card,
                         region: Region = Region.OPPONENT_HAND) -> Fraction:
        state = self.state(state)
        region = Region(region)
        if card not in state.deck.cards:
            raise ValueError("Card not in universe")
        if card in state.known_cards:
            return Fraction(int(region == Region.OPPONENT_HAND and card in state.opponent_known_cards))
        return Fraction(state.region_size(region), len(state.unknown_cards))

    def all_cards_probability(self, state: GameState | ProbabilityState, cards: Iterable[Card],
                              region: Region = Region.OPPONENT_HAND) -> Fraction:
        state = self.state(state)
        region = Region(region)
        cards = validate_unique(cards)
        state.deck.remove_known(cards)
        hidden_required = 0
        for card in cards:
            if card in state.known_cards:
                if region != Region.OPPONENT_HAND or card not in state.opponent_known_cards:
                    return Fraction()
            else:
                hidden_required += 1
        n = len(state.unknown_cards)
        size = state.region_size(region)
        return Fraction(combinations_count(n-hidden_required, size-hidden_required), comb(n,size))

    def matching_count_distribution(self, state: GameState | ProbabilityState, predicate: Callable[[Card], bool],
                                    region: Region = Region.OPPONENT_HAND) -> tuple[Fraction, ...]:
        """Index k is P(total matching cards in the selected region == k)."""
        state = self.state(state)
        region = Region(region)
        known_matches = sum(bool(predicate(c)) for c in state.opponent_known_cards) if region == Region.OPPONENT_HAND else 0
        successes = sum(bool(predicate(c)) for c in state.unknown_cards)
        hidden = hypergeometric_pmf(len(state.unknown_cards), successes, state.region_size(region))
        # Full opponent-hand support includes known nonmatching cards as trailing zeros.
        known_count = len(state.opponent_known_cards) if region == Region.OPPONENT_HAND else 0
        return (Fraction(),) * known_matches + hidden + (Fraction(),) * (known_count-known_matches)

    def at_least_one_probability(self, state: GameState | ProbabilityState, predicate: Callable[[Card], bool],
                                 region: Region = Region.OPPONENT_HAND) -> Fraction:
        return 1 - self.matching_count_distribution(state, predicate, region)[0]

    def next_draw_probability(self, state: GameState | ProbabilityState, predicate: Callable[[Card], bool]) -> Fraction:
        """Uniform hidden draw order; no draw-order information is present in GameState."""
        state = self.state(state)
        if not state.draw_pile_size:
            raise ValueError("No next draw: draw pile is empty")
        return Fraction(sum(bool(predicate(c)) for c in state.unknown_cards), len(state.unknown_cards))
