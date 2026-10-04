from dataclasses import dataclass, field, replace
from enum import StrEnum

from engine.cards import Card, Deck, validate_unique


class Player(StrEnum):
    PLAYER = "player"
    OPPONENT = "opponent"


@dataclass(frozen=True, slots=True)
class PlayerCounts:
    player: int = 0
    opponent: int = 0

    def __post_init__(self) -> None:
        if any(type(n) is not int or n < 0 for n in (self.player, self.opponent)):
            raise ValueError("Counts must be nonnegative integers")


@dataclass(frozen=True, slots=True)
class CapturedCards:
    player: tuple[Card, ...] = ()
    opponent: tuple[Card, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "player", validate_unique(self.player))
        object.__setattr__(self, "opponent", validate_unique(self.opponent))
        validate_unique(self.player + self.opponent)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    turn_number: int
    actor: Player
    played_card: Card
    captured_cards: tuple[Card, ...] = ()

    def __post_init__(self) -> None:
        if type(self.turn_number) is not int or self.turn_number < 0:
            raise ValueError("Invalid history turn")
        object.__setattr__(self, "actor", Player(self.actor))
        object.__setattr__(self, "captured_cards", validate_unique(self.captured_cards))
        validate_unique((self.played_card,) + self.captured_cards)


@dataclass(frozen=True, slots=True)
class GameState:
    # Full card universe, NOT an ordered remaining draw pile. Its order carries no hidden information.
    deck: Deck = field(default_factory=Deck.create)
    table_cards: tuple[Card, ...] = ()
    player_hand: tuple[Card, ...] = ()
    opponent_known_cards: tuple[Card, ...] = ()
    # Historical ledger: may overlap table/captured zones, never current hands.
    played_cards: tuple[Card, ...] = ()
    captured_cards: CapturedCards = field(default_factory=CapturedCards)
    current_player: Player = Player.PLAYER
    turn_number: int = 0
    round_number: int = 1
    player_score: int = 0
    opponent_score: int = 0
    scopa_count: PlayerCounts = field(default_factory=PlayerCounts)
    game_history: tuple[HistoryEntry, ...] = ()
    opponent_hand_size: int = 0
    draw_pile_size: int = 0
    last_capture_player: Player | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.deck, Deck) or not isinstance(self.captured_cards, CapturedCards):
            raise TypeError("Invalid deck or captured cards")
        if not isinstance(self.scopa_count, PlayerCounts):
            raise TypeError("Invalid scopa count")
        for name in ("table_cards", "player_hand", "opponent_known_cards", "played_cards"):
            object.__setattr__(self, name, validate_unique(getattr(self, name)))
        object.__setattr__(self, "current_player", Player(self.current_player))
        if self.last_capture_player is not None:
            object.__setattr__(self, "last_capture_player", Player(self.last_capture_player))
        object.__setattr__(self, "game_history", tuple(self.game_history))
        if any(not isinstance(e, HistoryEntry) for e in self.game_history):
            raise TypeError("History must contain HistoryEntry instances")
        for name in ("turn_number", "round_number", "player_score", "opponent_score",
                     "opponent_hand_size", "draw_pile_size"):
            n = getattr(self, name)
            if type(n) is not int or n < (1 if name == "round_number" else 0):
                raise ValueError(f"Invalid {name}")
        zones = (self.table_cards + self.player_hand + self.opponent_known_cards
                 + self.captured_cards.player + self.captured_cards.opponent)
        validate_unique(zones)
        self.deck.remove_known(zones)
        self.deck.remove_known(self.played_cards)
        hand_ids = {c.id for c in self.player_hand + self.opponent_known_cards}
        if any(c.id in hand_ids for c in self.played_cards):
            raise ValueError("Played cards cannot remain in a hand")
        for entry in self.game_history:
            self.deck.remove_known((entry.played_card,) + entry.captured_cards)
            if entry.played_card not in self.played_cards or entry.turn_number > self.turn_number:
                raise ValueError("History contradicts played ledger or turn number")
        turns = tuple(e.turn_number for e in self.game_history)
        if turns != tuple(sorted(set(turns))):
            raise ValueError("History turns must be strictly increasing")
        if self.opponent_hand_size < len(self.opponent_known_cards):
            raise ValueError("Known opponent cards exceed hand size")
        if self.hidden_opponent_count + self.draw_pile_size > len(self.unknown_cards):
            raise ValueError("Hidden card counts exceed unknown pool")

    @property
    def known_cards(self) -> tuple[Card, ...]:
        cards = (self.table_cards + self.player_hand + self.opponent_known_cards
                 + self.played_cards + self.captured_cards.player + self.captured_cards.opponent)
        return tuple({c.id: c for c in cards}.values())

    @property
    def unknown_cards(self) -> tuple[Card, ...]:
        return self.deck.unknown_cards(self.known_cards)

    @property
    def hidden_opponent_count(self) -> int:
        return self.opponent_hand_size - len(self.opponent_known_cards)

    def evolve(self, **changes: object) -> "GameState":
        """Validated replacement; move legality will be enforced by the rules module."""
        return replace(self, **changes)
