from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from engine.cards import Deck
from engine.game_state import Player

Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Positive = Annotated[int, Field(strict=True, gt=0)]


class Schema(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class CardSchema(Schema):
    id: str
    suit: str
    rank: Positive
    value: Positive


def standard_deck():
    return [CardSchema(id=c.id, suit=c.suit, rank=c.rank, value=c.value) for c in Deck.create().cards]


class CountsSchema(Schema):
    player: Nonnegative = 0
    opponent: Nonnegative = 0


class CapturedSchema(Schema):
    player: list[str] = Field(default_factory=list)
    opponent: list[str] = Field(default_factory=list)


class HistorySchema(Schema):
    turn_number: Nonnegative
    actor: Player
    played_card: str
    captured_cards: list[str] = Field(default_factory=list)


class GameStateSchema(Schema):
    deck: list[CardSchema] = Field(default_factory=standard_deck, min_length=1)
    table_cards: list[str] = Field(default_factory=list)
    player_hand: list[str] = Field(default_factory=list)
    opponent_known_cards: list[str] = Field(default_factory=list)
    played_cards: list[str] = Field(default_factory=list)
    captured_cards: CapturedSchema = Field(default_factory=CapturedSchema)
    current_player: Player = Player.PLAYER
    turn_number: Nonnegative = 0
    round_number: Positive = 1
    player_score: Nonnegative = 0
    opponent_score: Nonnegative = 0
    scopa_count: CountsSchema = Field(default_factory=CountsSchema)
    game_history: list[HistorySchema] = Field(default_factory=list)
    opponent_hand_size: Nonnegative = 0
    draw_pile_size: Nonnegative = 0
    last_capture_player: Player | None = None


class CreateGameRequest(Schema):
    state: GameStateSchema = Field(default_factory=GameStateSchema)


class UpdateStateRequest(Schema):
    state: GameStateSchema
    expected_revision: Positive | None = None


class GameResponse(Schema):
    id: UUID
    revision: Positive
    state: GameStateSchema
    has_analysis: bool
    has_simulation: bool


class AnalyzeRequest(Schema):
    max_depth: Annotated[int, Field(strict=True, ge=1, le=12)] = 2
    max_nodes: Annotated[int, Field(strict=True, ge=1, le=100_000)] = 5_000
    max_belief_worlds: Annotated[int, Field(strict=True, ge=1, le=100_000)] = 10_000
    max_exact_worlds: Annotated[int, Field(strict=True, ge=1, le=100_000)] = 10_000
    monte_carlo_samples: Annotated[int, Field(strict=True, ge=1, le=100_000)] = 10_000
    probability_method: Literal['auto', 'exact', 'monte_carlo'] = 'auto'
    seed: Annotated[int, Field(strict=True)] = 0
    cards_per_hand: Annotated[int, Field(strict=True, ge=1, le=40)] = 3
    first_player: Player = Player.PLAYER


class ForcedMoveSchema(Schema):
    played_card: str
    captured_cards: list[str] = Field(default_factory=list)


class SimulateRequest(Schema):
    iterations: Annotated[int, Field(strict=True, ge=1, le=1_000_000)] = 1000
    seed: Annotated[int, Field(strict=True)] = 0
    max_depth: Annotated[int, Field(strict=True, ge=0, le=100)] = 6
    workers: Annotated[int, Field(strict=True, ge=1, le=8)] = 1
    chunk_size: Annotated[int, Field(strict=True, ge=1, le=10_000)] = 128
    confidence: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)] = .95
    trace_limit: Annotated[int, Field(strict=True, ge=0, le=100)] = 0
    cards_per_hand: Annotated[int, Field(strict=True, ge=1, le=40)] = 3
    first_player: Player = Player.PLAYER
    player_policy: Literal['greedy', 'first_legal'] = 'greedy'
    move: ForcedMoveSchema | None = None
