from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    suit: str
    rank: int
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Card id must be a nonempty string")
        if not isinstance(self.suit, str) or not self.suit.strip():
            raise ValueError("Card suit must be a nonempty string")
        for name in ("rank", "value"):
            number = getattr(self, name)
            if type(number) is not int or number <= 0:
                raise ValueError(f"Card {name} must be a positive integer")
