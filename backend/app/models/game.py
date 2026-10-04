from dataclasses import dataclass
from uuid import UUID
from engine.game_state import GameState
from engine.decision_engine import AnalysisResult
from engine.simulation import SimulationResult


@dataclass(frozen=True, slots=True)
class GameRecord:
    id: UUID
    revision: int
    state: GameState
    analysis: AnalysisResult | None = None
    simulation: SimulationResult | None = None
