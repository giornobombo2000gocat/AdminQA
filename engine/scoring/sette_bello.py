from engine.game_state import CapturedCards
from .common import compare, validate_captures
from .config import ScoringConfig
from .models import CategoryScore


def score_sette_bello(captures: CapturedCards, config: ScoringConfig | None = None) -> CategoryScore:
    config = config or ScoringConfig()
    validate_captures(captures, config)
    def owns(cards):
        return int(any(c.suit == config.denari_suit and c.rank == config.sette_bello_rank for c in cards))
    return compare(owns(captures.player), owns(captures.opponent), config.sette_bello_points)
