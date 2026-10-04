from dataclasses import dataclass, field

from engine.cards import DeckConfig


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    deck_config: DeckConfig = field(default_factory=DeckConfig)
    denari_suit: str = "denari"
    sette_bello_rank: int = 7
    primiera_values: tuple[tuple[int, int], ...] = (
        (1, 16), (2, 12), (3, 13), (4, 14), (5, 15),
        (6, 18), (7, 21), (8, 10), (9, 10), (10, 10),
    )
    captured_cards_points: int = 1
    scopa_points: int = 1
    denari_points: int = 1
    sette_bello_points: int = 1
    primiera_points: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.deck_config, DeckConfig):
            raise TypeError("Expected DeckConfig")
        object.__setattr__(self, "primiera_values", tuple(tuple(pair) for pair in self.primiera_values))
        if self.denari_suit not in self.deck_config.suits:
            raise ValueError("Denari suit is not configured")
        if type(self.sette_bello_rank) is not int or self.sette_bello_rank not in self.deck_config.ranks:
            raise ValueError("Sette Bello rank is not configured")
        if any(len(pair) != 2 for pair in self.primiera_values):
            raise ValueError("Primiera entries must be rank/value pairs")
        if any(type(n) is not int or n <= 0 for pair in self.primiera_values for n in pair):
            raise ValueError("Primiera ranks and values must be positive integers")
        ranks = tuple(rank for rank, _ in self.primiera_values)
        if len(set(ranks)) != len(ranks) or set(ranks) != set(self.deck_config.ranks):
            raise ValueError("Primiera must define every configured rank exactly once")
        for name in ("captured_cards_points", "scopa_points", "denari_points", "sette_bello_points", "primiera_points"):
            n = getattr(self, name)
            if type(n) is not int or n < 0:
                raise ValueError(f"Invalid {name}")
