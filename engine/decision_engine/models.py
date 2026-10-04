from dataclasses import dataclass, field
from fractions import Fraction

from engine.game_tree import PositionEvaluation, SearchResult
from engine.moves import Move
from engine.probabilities import ProbabilityDistribution


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    node_id: int
    probability: Fraction
    player_evaluation: PositionEvaluation
    opponent_evaluation: PositionEvaluation
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


@dataclass(frozen=True, slots=True)
class MoveAnalysis:
    move: Move
    node_id: int
    evaluation: PositionEvaluation
    expected_evaluation: PositionEvaluation
    expected_value: Fraction
    player_expected_value: Fraction
    opponent_expected_value: Fraction
    scopa_probability: Fraction
    opponent_scopa_probability: Fraction
    expected_scopa_count: Fraction
    primiera_value: Fraction
    opponent_primiera_value: Fraction
    primiera_eligible_probability: Fraction
    sette_bello_value: Fraction
    sette_bello_probability: Fraction
    expected_captured_cards: Fraction
    terminal_probability: Fraction
    outcomes: tuple[OutcomeEvaluation, ...]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    all_moves: tuple[MoveAnalysis, ...]
    recommended_move: Move | None
    tree: SearchResult | None
    probabilities: ProbabilityDistribution | None
    search_depth: int
    reached_depth: int
    status: str
    calculation_time: float = field(compare=False)

    @property
    def legal_moves(self) -> tuple[Move, ...]:
        return tuple(item.move for item in self.all_moves)

    @property
    def recommended_analysis(self) -> MoveAnalysis | None:
        return next((item for item in self.all_moves if item.move==self.recommended_move),None)

    @property
    def expected_value(self) -> Fraction | None:
        return self.recommended_analysis.expected_value if self.recommended_analysis else None

    @property
    def scopa_probability(self) -> Fraction | None:
        return self.recommended_analysis.scopa_probability if self.recommended_analysis else None

    @property
    def primiera_value(self) -> Fraction | None:
        return self.recommended_analysis.primiera_value if self.recommended_analysis else None

    @property
    def sette_bello_value(self) -> Fraction | None:
        return self.recommended_analysis.sette_bello_value if self.recommended_analysis else None

    @property
    def opponent_expected_value(self) -> Fraction | None:
        return self.recommended_analysis.opponent_expected_value if self.recommended_analysis else None

    @property
    def exact_probabilities(self) -> bool | None:
        return self.probabilities.exact if self.probabilities else None
