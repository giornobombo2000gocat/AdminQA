from engine.game_state import CapturedCards
from .common import compare, validate_captures
from .config import ScoringConfig
from .models import CategoryScore


def score_captured_cards(captures: CapturedCards, config: ScoringConfig | None = None) -> CategoryScore:
    config = config or ScoringConfig()
    validate_captures(captures, config)
    return compare(len(captures.player), len(captures.opponent), config.captured_cards_points)
