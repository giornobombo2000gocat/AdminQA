from uuid import UUID
from typing import Literal

from .games import CardSchema, GameStateSchema, Player, Positive, Nonnegative, Schema


class RationalSchema(Schema):
    numerator: int
    denominator: Positive


class EvaluationSchema(Schema):
    source: str
    captured_cards: RationalSchema
    scopa: RationalSchema
    denari: RationalSchema
    sette_bello: RationalSchema
    primiera: RationalSchema
    previous_score: RationalSchema
    total: RationalSchema


class MoveSchema(Schema):
    played_card: CardSchema
    captured_cards: list[CardSchema]
    actor: Player
    capture_type: str
    creates_scopa: bool
    immediate_score: int
    resulting_state: GameStateSchema


class OutcomeSchema(Schema):
    node_id: Nonnegative
    probability: RationalSchema
    player_evaluation: EvaluationSchema
    opponent_evaluation: EvaluationSchema
    player_scopa_delta: int
    opponent_scopa_delta: int
    primiera_value: int
    opponent_primiera_value: int
    primiera_eligible: bool
    opponent_primiera_eligible: bool
    sette_bello_owned: bool
    opponent_sette_bello_owned: bool
    sette_bello_points: int
    opponent_sette_bello_points: int
    captured_cards: int
    opponent_captured_cards: int


class MoveAnalysisSchema(Schema):
    move: MoveSchema
    node_id: Nonnegative
    evaluation: EvaluationSchema
    expected_evaluation: EvaluationSchema
    expected_value: RationalSchema
    player_expected_value: RationalSchema
    opponent_expected_value: RationalSchema
    scopa_probability: RationalSchema
    opponent_scopa_probability: RationalSchema
    expected_scopa_count: RationalSchema
    primiera_value: RationalSchema
    opponent_primiera_value: RationalSchema
    primiera_eligible_probability: RationalSchema
    sette_bello_value: RationalSchema
    sette_bello_probability: RationalSchema
    expected_captured_cards: RationalSchema
    terminal_probability: RationalSchema
    outcomes: list[OutcomeSchema]


class ProbabilitySummarySchema(Schema):
    method: Literal['exact','monte_carlo']
    exact: bool
    seed: int | None
    sample_count: int | None
    world_count: Positive
    known_cards: list[str]
    unknown_cards: list[str]


class AnalysisResponse(Schema):
    game_id: UUID
    state_revision: Positive
    status: str
    all_moves: list[MoveAnalysisSchema]
    recommended_move: MoveSchema | None
    expected_value: RationalSchema | None
    scopa_probability: RationalSchema | None
    primiera_value: RationalSchema | None
    sette_bello_value: RationalSchema | None
    opponent_expected_value: RationalSchema | None
    probabilities: ProbabilitySummarySchema | None
    search_depth: Nonnegative
    reached_depth: Nonnegative
    explored_states: Nonnegative
    calculation_time_seconds: float


class MeanEstimateSchema(Schema):
    name: str
    samples: Positive
    mean: RationalSchema
    sample_variance: RationalSchema | None
    standard_error: float | None
    confidence: float
    confidence_interval: tuple[float,float] | None
    hoeffding_error_bound: float
    hoeffding_interval: tuple[float,float]


class ProportionEstimateSchema(Schema):
    name: str
    samples: Positive
    successes: Nonnegative
    probability: RationalSchema
    standard_error: float
    confidence: float
    confidence_interval: tuple[float,float]
    interval_method: str


class SimulationEventSchema(Schema):
    kind: str
    move: MoveSchema | None
    player_drawn_cards: list[CardSchema]


class TraceSchema(Schema):
    iteration: Nonnegative
    final_state: GameStateSchema
    moves_played: Nonnegative
    evaluation_source: str
    events: list[SimulationEventSchema]


class SimulationResponse(Schema):
    game_id: UUID
    state_revision: Positive
    iterations: Positive
    seed: int
    max_depth: Nonnegative
    reached_depth: Nonnegative
    player_policy: str
    means: list[MeanEstimateSchema]
    proportions: list[ProportionEstimateSchema]
    traces: list[TraceSchema]
    workers: Positive
    chunk_size: Positive
    calculation_time_seconds: float
