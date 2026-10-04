from dataclasses import dataclass, field
from fractions import Fraction

from engine.cards import Card
from engine.game_state import GameState
from engine.moves import Move


@dataclass(frozen=True, slots=True)
class MeanEstimate:
    name: str
    samples: int
    mean: Fraction
    sample_variance: Fraction | None
    standard_error: float | None
    confidence: float
    confidence_interval: tuple[float,float] | None
    hoeffding_error_bound: float
    hoeffding_interval: tuple[float,float]


@dataclass(frozen=True, slots=True)
class ProportionEstimate:
    name: str
    samples: int
    successes: int
    probability: Fraction
    standard_error: float
    confidence: float
    confidence_interval: tuple[float,float]
    interval_method: str = "wilson"


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    kind: str
    move: Move | None = None
    player_drawn_cards: tuple[Card,...] = ()


@dataclass(frozen=True, slots=True)
class RolloutTrace:
    iteration: int
    final_state: GameState
    moves_played: int
    evaluation_source: str
    events: tuple[SimulationEvent,...]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    iterations: int
    seed: int
    max_depth: int
    reached_depth: int
    player_policy: str
    means: tuple[MeanEstimate,...]
    proportions: tuple[ProportionEstimate,...]
    traces: tuple[RolloutTrace,...]
    workers: int = field(compare=False)
    chunk_size: int = field(compare=False)
    calculation_time: float = field(compare=False)

    def metric(self,name: str) -> MeanEstimate:
        return next(item for item in self.means if item.name==name)

    def event(self,name: str) -> ProportionEstimate:
        return next(item for item in self.proportions if item.name==name)

    @property
    def expected_value(self) -> MeanEstimate:
        return self.metric("expected_value")

    @property
    def scopa_probability(self) -> ProportionEstimate:
        return self.event("player_scopa")

    @property
    def opponent_scopa_probability(self) -> ProportionEstimate:
        return self.event("opponent_scopa")


@dataclass(frozen=True, slots=True)
class ExactSimulationResult:
    metrics: tuple[tuple[str,Fraction],...]
    probabilities: tuple[tuple[str,Fraction],...]
    explored_nodes: int


@dataclass(frozen=True, slots=True)
class ComparisonMetric:
    name: str
    exact: Fraction
    monte_carlo: Fraction
    absolute_error: Fraction
    confidence_interval: tuple[float,float] | None
    exact_inside_interval: bool | None


@dataclass(frozen=True, slots=True)
class SimulationComparison:
    exact: ExactSimulationResult
    simulation: SimulationResult
    comparisons: tuple[ComparisonMetric,...]
