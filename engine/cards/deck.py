from dataclasses import dataclass
from random import Random
from collections.abc import Iterable

from .config import DeckConfig
from .models import Card


def validate_unique(cards: Iterable[Card]) -> tuple[Card, ...]:
    cards = tuple(cards)
    if any(not isinstance(card, Card) for card in cards):
        raise TypeError("Expected Card instances")
    if len({c.id for c in cards}) != len(cards):
        raise ValueError("Duplicate card ids")
    if len({(c.suit, c.rank) for c in cards}) != len(cards):
        raise ValueError("Duplicate physical cards")
    return cards


@dataclass(frozen=True, slots=True)
class Deck:
    cards: tuple[Card, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cards", validate_unique(self.cards))

    @classmethod
    def create(cls, config: DeckConfig | None = None) -> "Deck":
        config = config or DeckConfig()
        return cls(tuple(Card(f"{suit}:{rank}", suit, rank, value)
                         for suit in config.suits
                         for rank, value in zip(config.ranks, config.values, strict=True)))

    def shuffle(self, seed: int) -> "Deck":
        if type(seed) is not int:
            raise ValueError("An integer seed is required")
        cards = list(self.cards)
        Random(seed).shuffle(cards)
        return Deck(tuple(cards))

    def deal(self, count: int) -> tuple[tuple[Card, ...], "Deck"]:
        if type(count) is not int or not 0 <= count <= len(self.cards):
            raise ValueError("Invalid deal count")
        return self.cards[:count], Deck(self.cards[count:])

    def remove_known(self, known: Iterable[Card]) -> "Deck":
        known = validate_unique(known)
        by_id = {c.id: c for c in self.cards}
        if any(by_id.get(c.id) != c for c in known):
            raise ValueError("Known card does not belong to this deck")
        ids = {c.id for c in known}
        return Deck(tuple(c for c in self.cards if c.id not in ids))

    def unknown_cards(self, known: Iterable[Card]) -> tuple[Card, ...]:
        return self.remove_known(known).cards
