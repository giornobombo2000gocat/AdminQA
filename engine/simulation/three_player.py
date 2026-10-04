"""Compatibility exports for the three-player simulator."""
from .multiplayer import MultiplayerState as ThreeState, MultiplayerMove as ThreeMove, MultiplayerResult as ThreeResult
from .multiplayer import legal_moves, apply_move, final_points, recommend, category_values, public_utility, move_key
from .multiplayer import play_round as play_three_round, play_batch as play_three_batch
