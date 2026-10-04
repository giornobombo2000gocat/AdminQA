from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from engine.cards import Card
from engine.game_state import GameState
from engine.moves import Move
from engine.probabilities import ProbabilityDistribution
from .evaluation import PositionEvaluation


class NodeKind(StrEnum):
    PLAYER = "player"
    OPPONENT = "opponent"
    CHANCE = "chance"
    TERMINAL = "terminal"
    CUTOFF = "cutoff"


class EdgeKind(StrEnum):
    ROOT = "root"
    PLAYER_MOVE = "player_move"
    OPPONENT_MOVE = "opponent_move"
    UNKNOWN_CARD = "unknown_card"


@dataclass(frozen=True, slots=True)
class TreeNode:
    id: int
    parent_id: int | None
    state: GameState
    belief: ProbabilityDistribution
    depth: int
    probability: Fraction
    branch_probability: Fraction | None
    edge_kind: EdgeKind
    kind: NodeKind
    evaluation: PositionEvaluation
    value: Fraction
    move: Move | None = None
    drawn_card: Card | None = None
    children: tuple[int, ...] = ()
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    explored_states: tuple[TreeNode, ...]
    search_depth: int
    reached_depth: int
    probability_method: str
    seed: int | None
    sample_count: int | None

    @property
    def root(self) -> TreeNode:
        return self.explored_states[0]

    @property
    def node_count(self) -> int:
        return len(self.explored_states)

    @property
    def unique_state_count(self) -> int:
        return len({node.state for node in self.explored_states})
