from dataclasses import dataclass

from engine.game_state import Player


@dataclass(frozen=True, slots=True)
class SearchConfig:
    max_depth: int = 2
    max_nodes: int = 5_000
    max_belief_worlds: int = 10_000
    cards_per_hand: int = 3
    first_player: Player = Player.PLAYER
    probability_method: str = "auto"

    def __post_init__(self) -> None:
        if type(self.max_depth) is not int or self.max_depth < 0:
            raise ValueError("max_depth must be a nonnegative integer")
        for name in ("max_nodes", "max_belief_worlds", "cards_per_hand"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"Invalid {name}")
        object.__setattr__(self, "first_player", Player(self.first_player))
        if self.probability_method not in ("auto", "exact", "monte_carlo"):
            raise ValueError("Invalid probability method")
