from fractions import Fraction
from typing import Protocol

from engine.game_state import GameState
from engine.moves import Move


class OpponentModel(Protocol):
    def probabilities(self, state: GameState, moves: tuple[Move, ...]) -> tuple[Fraction, ...]:
        """Action weights for a concrete opponent hand; must sum to one."""
        ...


class UniformOpponent:
    def probabilities(self, state: GameState, moves: tuple[Move, ...]) -> tuple[Fraction, ...]:
        """All legal actions equally likely; no random action is selected."""
        if not moves:
            return ()
        return (Fraction(1, len(moves)),) * len(moves)
