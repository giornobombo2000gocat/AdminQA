from dataclasses import dataclass
from enum import StrEnum

from engine.cards import Card, validate_unique
from engine.game_state import GameState, Player


class CaptureType(StrEnum):
    NONE = "none"
    SINGLE = "single"
    SUM = "sum"


@dataclass(frozen=True, slots=True)
class Move:
    played_card: Card
    captured_cards: tuple[Card, ...] = ()
    actor: Player = Player.PLAYER
    capture_type: CaptureType = CaptureType.NONE
    creates_scopa: bool = False
    immediate_score: int = 0
    resulting_state: GameState | None = None

    def __post_init__(self) -> None:
        validate_unique((self.played_card,))
        object.__setattr__(self, "captured_cards", validate_unique(self.captured_cards))
        object.__setattr__(self, "actor", Player(self.actor))
        object.__setattr__(self, "capture_type", CaptureType(self.capture_type))

    @property
    def is_capture(self) -> bool:
        """Whether the action selects table cards (legality requires rule evaluation)."""
        return bool(self.captured_cards)

    @property
    def is_discard(self) -> bool:
        return not self.is_capture

    @property
    def resulting_table_cards(self) -> tuple[Card, ...] | None:
        """None means unevaluated; an empty tuple means the resulting table is empty."""
        return None if self.resulting_state is None else self.resulting_state.table_cards
