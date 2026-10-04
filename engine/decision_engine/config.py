from dataclasses import dataclass, field

from engine.game_tree import EvaluationConfig, SearchConfig
from engine.probabilities import ProbabilityConfig


@dataclass(frozen=True, slots=True)
class DecisionConfig:
    search: SearchConfig = field(default_factory=SearchConfig)
    probabilities: ProbabilityConfig = field(default_factory=ProbabilityConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.search,SearchConfig) or not isinstance(self.probabilities,ProbabilityConfig) or not isinstance(self.evaluation,EvaluationConfig):
            raise TypeError("Invalid decision configuration components")
        if self.search.max_depth<1:
            raise ValueError("Decision analysis needs search depth >= 1 to compare every legal move")
