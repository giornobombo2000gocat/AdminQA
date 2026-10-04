from engine.game_state import CapturedCards
from .common import compare, validate_captures
from .config import ScoringConfig
from .models import CategoryScore


def score_denari(captures: CapturedCards, config: ScoringConfig | None = None) -> CategoryScore:
    config = config or ScoringConfig()
    validate_captures(captures, config)
    return compare(sum(c.suit == config.denari_suit for c in captures.player),
                   sum(c.suit == config.denari_suit for c in captures.opponent), config.denari_points)
