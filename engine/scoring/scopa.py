from engine.game_state import PlayerCounts
from .config import ScoringConfig
from .models import ScopaScore


def score_scopa(counts: PlayerCounts, config: ScoringConfig | None = None) -> ScopaScore:
    if not isinstance(counts, PlayerCounts):
        raise TypeError("Expected PlayerCounts")
    config = config or ScoringConfig()
    return ScopaScore(counts, PlayerCounts(counts.player * config.scopa_points, counts.opponent * config.scopa_points))
