from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RulesConfig:
    single_card_priority: bool = True
    mandatory_capture: bool = True
    final_play_scopa: bool = False
    scopa_points: int = 1

    def __post_init__(self) -> None:
        for name in ("single_card_priority", "mandatory_capture", "final_play_scopa"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"Invalid {name}")
        if type(self.scopa_points) is not int or self.scopa_points < 0:
            raise ValueError("Invalid scopa points")
