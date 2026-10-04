from dataclasses import dataclass, field
from math import isfinite

from engine.game_state import Player
from engine.game_tree import EvaluationConfig
from engine.rules import RulesConfig
from engine.scoring import ScoringConfig


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    iterations: int = 1_000
    seed: int = 0
    max_depth: int = 6
    workers: int = 1
    chunk_size: int = 128
    confidence: float = 0.95
    trace_limit: int = 0
    cards_per_hand: int = 3
    first_player: Player = Player.PLAYER
    player_policy: str = "greedy"
    max_exact_worlds: int = 10_000
    max_exact_nodes: int = 10_000
    rules: RulesConfig = field(default_factory=RulesConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)

    def __post_init__(self) -> None:
        for name in ("iterations","workers","chunk_size","cards_per_hand","max_exact_worlds","max_exact_nodes"):
            if type(getattr(self,name)) is not int or getattr(self,name)<=0:
                raise ValueError(f"{name} must be positive")
        for name in ("max_depth","trace_limit"):
            if type(getattr(self,name)) is not int or getattr(self,name)<0:
                raise ValueError(f"Invalid {name}")
        if type(self.seed) is not int:
            raise ValueError("Seed must be an integer")
        if type(self.confidence) not in (int,float) or not isfinite(self.confidence) or not 0<self.confidence<1:
            raise ValueError("Confidence must be finite and between zero and one")
        if self.player_policy not in ("greedy","first_legal"):
            raise ValueError("Unknown player policy")
        if not isinstance(self.rules,RulesConfig) or not isinstance(self.scoring,ScoringConfig) or not isinstance(self.evaluation,EvaluationConfig):
            raise TypeError("Invalid rules, scoring or evaluation configuration")
        if self.rules.scopa_points!=self.scoring.scopa_points:
            raise ValueError("Rules/scoring Scopa weights must agree")
        object.__setattr__(self,"first_player",Player(self.first_player))
