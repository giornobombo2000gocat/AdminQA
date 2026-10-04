from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from math import comb, sqrt

from engine.cards import Card, Deck, validate_unique
from engine.game_state import GameState


class Region(StrEnum):
    OPPONENT_HAND = "opponent_hand"
    DRAW_PILE = "draw_pile"
    UNASSIGNED = "unassigned"


def canonical(cards) -> tuple[Card, ...]:
    return tuple(sorted(validate_unique(cards), key=lambda c: c.id))


@dataclass(frozen=True, slots=True)
class PossibleWorld:
    # Unordered sets, canonically stored. Opponent hand includes its known cards.
    opponent_hand: tuple[Card, ...]
    draw_pile: tuple[Card, ...]
    unassigned: tuple[Card, ...] = ()

    def __post_init__(self) -> None:
        for name in ("opponent_hand", "draw_pile", "unassigned"):
            object.__setattr__(self, name, canonical(getattr(self, name)))
        validate_unique(self.opponent_hand + self.draw_pile + self.unassigned)

    def cards_in(self, region: Region) -> tuple[Card, ...]:
        return getattr(self, Region(region).value)


@dataclass(frozen=True, slots=True)
class ProbabilityState:
    deck: Deck
    known_cards: tuple[Card, ...]
    unknown_cards: tuple[Card, ...]
    opponent_known_cards: tuple[Card, ...]
    hidden_opponent_count: int
    draw_pile_size: int

    def __post_init__(self) -> None:
        if not isinstance(self.deck, Deck):
            raise TypeError("Expected Deck")
        # Deck order must not leak hidden dealing information into a belief state.
        object.__setattr__(self, "deck", Deck(canonical(self.deck.cards)))
        for name in ("known_cards", "unknown_cards", "opponent_known_cards"):
            object.__setattr__(self, name, canonical(getattr(self, name)))
        validate_unique(self.known_cards + self.unknown_cards)
        if set(self.known_cards + self.unknown_cards) != set(self.deck.cards):
            raise ValueError("Known and unknown cards must partition the card universe")
        if not set(self.opponent_known_cards) <= set(self.known_cards):
            raise ValueError("Known opponent cards must be known cards")
        for name in ("hidden_opponent_count", "draw_pile_size"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"Invalid {name}")
        if self.hidden_opponent_count + self.draw_pile_size > len(self.unknown_cards):
            raise ValueError("Hidden region sizes exceed the unknown pool")

    @classmethod
    def from_game_state(cls, state: GameState) -> "ProbabilityState":
        return cls(state.deck, state.known_cards, state.unknown_cards,
                   state.opponent_known_cards, state.hidden_opponent_count, state.draw_pile_size)

    @property
    def unassigned_count(self) -> int:
        return len(self.unknown_cards) - self.hidden_opponent_count - self.draw_pile_size

    @property
    def world_count(self) -> int:
        n = len(self.unknown_cards)
        return comb(n, self.hidden_opponent_count) * comb(n - self.hidden_opponent_count, self.draw_pile_size)

    def region_size(self, region: Region) -> int:
        return {Region.OPPONENT_HAND: self.hidden_opponent_count,
                Region.DRAW_PILE: self.draw_pile_size,
                Region.UNASSIGNED: self.unassigned_count}[Region(region)]

    def validate_world(self, world: PossibleWorld) -> None:
        if not isinstance(world, PossibleWorld):
            raise TypeError("Expected PossibleWorld")
        if not set(self.opponent_known_cards) <= set(world.opponent_hand):
            raise ValueError("World omits known opponent cards")
        hidden = tuple(c for c in world.opponent_hand if c not in self.opponent_known_cards)
        if (len(hidden) != self.hidden_opponent_count or len(world.draw_pile) != self.draw_pile_size
                or len(world.unassigned) != self.unassigned_count):
            raise ValueError("World has incorrect region sizes")
        if set(hidden + world.draw_pile + world.unassigned) != set(self.unknown_cards):
            raise ValueError("World does not partition the unknown pool")


@dataclass(frozen=True, slots=True)
class WeightedWorld:
    world: PossibleWorld
    probability: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.world, PossibleWorld) or not isinstance(self.probability, Fraction):
            raise TypeError("Expected PossibleWorld and Fraction")
        if not 0 < self.probability <= 1:
            raise ValueError("World probability must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ProbabilityEstimate:
    probability: Fraction
    exact: bool
    sample_count: int | None
    standard_error: float | None


@dataclass(frozen=True, slots=True)
class ProbabilityDistribution:
    state: ProbabilityState
    worlds: tuple[WeightedWorld, ...]
    method: str
    sample_count: int | None = None
    seed: int | None = None
    conditioned: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "worlds", tuple(self.worlds))
        if self.method not in ("exact", "monte_carlo"):
            raise ValueError("Unknown distribution method")
        if self.method == "exact":
            if self.sample_count is not None or self.seed is not None:
                raise ValueError("Exact enumeration has no sampling metadata")
        elif type(self.sample_count) is not int or self.sample_count <= 0 or type(self.seed) is not int:
            raise ValueError("Monte Carlo requires positive sample count and integer seed")
        for item in self.worlds:
            self.state.validate_world(item.world)
        if len({item.world for item in self.worlds}) != len(self.worlds):
            raise ValueError("Duplicate world entries; aggregate their weights")
        if self.total_mass != 1:
            raise ValueError("Distribution probabilities must sum to exactly 1")

    @property
    def exact(self) -> bool:
        return self.method == "exact"

    @property
    def total_mass(self) -> Fraction:
        return sum((item.probability for item in self.worlds), Fraction())

    def probability(self, event: Callable[[PossibleWorld], bool]) -> Fraction:
        return sum((item.probability for item in self.worlds if event(item.world)), Fraction())

    def estimate(self, event: Callable[[PossibleWorld], bool]) -> ProbabilityEstimate:
        p = self.probability(event)
        # After conditioning, the original sample count is not an effective sample size.
        error = None if self.exact or self.conditioned else sqrt(float(p * (1-p)) / self.sample_count)
        return ProbabilityEstimate(p, self.exact, self.sample_count, error)

    def condition(self, evidence: Callable[[PossibleWorld], bool]) -> "ProbabilityDistribution":
        selected = tuple(item for item in self.worlds if evidence(item.world))
        mass = sum((item.probability for item in selected), Fraction())
        if not mass:
            raise ValueError("Evidence has zero mass in this distribution")
        return ProbabilityDistribution(self.state,
            tuple(WeightedWorld(item.world, item.probability / mass) for item in selected),
            self.method, self.sample_count, self.seed, True)
