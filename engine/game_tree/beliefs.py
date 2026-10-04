from collections import defaultdict
from fractions import Fraction
from itertools import combinations
from math import comb

from engine.game_state import GameState
from engine.probabilities import PossibleWorld, ProbabilityDistribution, ProbabilityState, WeightedWorld


class SearchLimitExceeded(ValueError):
    """Search cannot complete within the configured resource bounds."""


def rebase(state: GameState, template: ProbabilityDistribution,
           weights: dict[PossibleWorld, Fraction], limit: int) -> ProbabilityDistribution:
    if len(weights) > limit:
        raise SearchLimitExceeded("Belief world limit exceeded")
    mass = sum(weights.values(), Fraction())
    if not mass:
        raise ValueError("Successor belief has zero probability")
    def key(world):
        return tuple(tuple(c.id for c in region) for region in (world.opponent_hand,world.draw_pile,world.unassigned))
    return ProbabilityDistribution(ProbabilityState.from_game_state(state),
        tuple(WeightedWorld(world,weights[world]/mass) for world in sorted(weights,key=key) if weights[world]),
        template.method, template.sample_count, template.seed, True)


def after_player_move(state: GameState, belief: ProbabilityDistribution, limit: int) -> ProbabilityDistribution:
    return rebase(state,belief,{item.world:item.probability for item in belief.worlds},limit)


def deal_hidden_opponent(state: GameState, template: ProbabilityDistribution,
                         weights: dict[PossibleWorld,Fraction], count: int, limit: int) -> ProbabilityDistribution:
    allocated = defaultdict(Fraction)
    for world,weight in weights.items():
        denominator=comb(len(world.draw_pile),count)
        for hand in combinations(world.draw_pile,count):
            rest=tuple(c for c in world.draw_pile if c not in hand)
            successor=PossibleWorld(world.opponent_hand+hand,rest,world.unassigned)
            allocated[successor]+=weight/denominator
            if len(allocated)>limit:
                raise SearchLimitExceeded("Opponent deal exceeds belief world limit")
    return rebase(state,template,allocated,limit)
