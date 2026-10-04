from dataclasses import replace
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from engine.game_state import GameState
from engine.decision_engine import AnalysisResult
from engine.simulation import SimulationResult
from backend.app.core.errors import GameNotFound, RevisionConflict
from backend.app.models.game import GameRecord


class GameRepository(Protocol):
    def create(self, state: GameState) -> GameRecord: ...
    def get(self, game_id: UUID) -> GameRecord: ...
    def replace_state(self, game_id: UUID, state: GameState, expected_revision: int | None) -> GameRecord: ...
    def save_analysis(self, game_id: UUID, revision: int, result: AnalysisResult) -> GameRecord: ...
    def save_simulation(self, game_id: UUID, revision: int, result: SimulationResult) -> GameRecord: ...


class InMemoryGameRepository:
    """One process, volatile storage. Immutable snapshots, atomic revision checks."""
    def __init__(self):
        self._records: dict[UUID, GameRecord] = {}
        self._lock = RLock()

    def create(self, state):
        with self._lock:
            record = GameRecord(uuid4(), 1, state)
            self._records[record.id] = record
            return record

    def get(self, game_id):
        with self._lock:
            try:
                return self._records[game_id]
            except KeyError:
                raise GameNotFound('Game not found') from None

    @staticmethod
    def _check_revision(record, expected):
        if expected is not None and record.revision != expected:
            raise RevisionConflict('Game state changed; retry using its current revision')

    def replace_state(self, game_id, state, expected_revision=None):
        with self._lock:
            record = self.get(game_id)
            self._check_revision(record, expected_revision)
            updated = GameRecord(game_id, record.revision + 1, state)
            self._records[game_id] = updated
            return updated

    def _save(self, game_id, revision, **changes):
        with self._lock:
            record = self.get(game_id)
            self._check_revision(record, revision)
            updated = replace(record, **changes)
            self._records[game_id] = updated
            return updated

    def save_analysis(self, game_id, revision, result):
        return self._save(game_id, revision, analysis=result)

    def save_simulation(self, game_id, revision, result):
        return self._save(game_id, revision, simulation=result)
