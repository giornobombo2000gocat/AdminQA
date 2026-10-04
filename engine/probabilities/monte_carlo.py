from collections import Counter
from fractions import Fraction
from random import Random

from .models import PossibleWorld, ProbabilityDistribution, ProbabilityState, WeightedWorld


def sample_worlds(state: ProbabilityState, samples: int, seed: int) -> ProbabilityDistribution:
    """Independent uniform world samples, aggregated into an empirical distribution."""
    if type(samples) is not int or samples <= 0 or type(seed) is not int:
        raise ValueError("Positive sample count and integer seed required")
    rng = Random(seed)
    counts: Counter[PossibleWorld] = Counter()
    h = state.hidden_opponent_count
    for _ in range(samples):
        selected = rng.sample(state.unknown_cards, h + state.draw_pile_size)
        hidden = tuple(selected[:h])
        draw = tuple(selected[h:])
        selected_set = set(selected)
        unassigned = tuple(c for c in state.unknown_cards if c not in selected_set)
        counts[PossibleWorld(state.opponent_known_cards + hidden, draw, unassigned)] += 1
    def key(world):
        return tuple(tuple(c.id for c in region) for region in (world.opponent_hand, world.draw_pile, world.unassigned))
    weights = tuple(WeightedWorld(world, Fraction(counts[world], samples)) for world in sorted(counts, key=key))
    return ProbabilityDistribution(state, weights, "monte_carlo", samples, seed)
