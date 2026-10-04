from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeckConfig:
    suits: tuple[str, ...] = ("denari", "coppe", "spade", "bastoni")
    ranks: tuple[int, ...] = tuple(range(1, 11))
    values: tuple[int, ...] = tuple(range(1, 11))

    def __post_init__(self) -> None:
        for name in ("suits", "ranks", "values"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.suits or any(not isinstance(s, str) or not s.strip() for s in self.suits):
            raise ValueError("Suits must be nonempty strings")
        if len(set(self.suits)) != len(self.suits):
            raise ValueError("Duplicate suits")
        if not self.ranks or len(self.ranks) != len(self.values):
            raise ValueError("Each rank needs a value")
        if len(set(self.ranks)) != len(self.ranks):
            raise ValueError("Duplicate ranks")
        if any(type(n) is not int or n <= 0 for n in (*self.ranks, *self.values)):
            raise ValueError("Ranks and values must be positive integers")
