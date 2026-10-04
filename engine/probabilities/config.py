from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProbabilityConfig:
    max_exact_worlds: int = 10_000
    monte_carlo_samples: int = 10_000
    seed: int = 0

    def __post_init__(self) -> None:
        for name in ("max_exact_worlds", "monte_carlo_samples"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.seed) is not int:
            raise ValueError("Seed must be an integer")
