from fractions import Fraction
from itertools import combinations

from .models import PossibleWorld, ProbabilityDistribution, ProbabilityState, WeightedWorld


class EnumerationLimitExceeded(ValueError):
    """Exact materialization exceeds the explicit resource limit."""


def enumerate_worlds(state: ProbabilityState, max_worlds: int) -> ProbabilityDistribution:
    if type(max_worlds) is not int or max_worlds <= 0:
        raise ValueError("max_worlds must be positive")
    if state.world_count > max_worlds:
        raise EnumerationLimitExceeded(f"{state.world_count} worlds exceeds limit {max_worlds}")
    weight = Fraction(1, state.world_count)
    worlds = []
    for hidden in combinations(state.unknown_cards, state.hidden_opponent_count):
        available = tuple(c for c in state.unknown_cards if c not in hidden)
        for draw in combinations(available, state.draw_pile_size):
            unassigned = tuple(c for c in available if c not in draw)
            worlds.append(WeightedWorld(PossibleWorld(state.opponent_known_cards + hidden, draw, unassigned), weight))
    return ProbabilityDistribution(state, tuple(worlds), "exact")
