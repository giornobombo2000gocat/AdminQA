from engine.cards import Card, Deck, validate_unique
from engine.game_state import CapturedCards, Player, PlayerCounts
from .common import compare, validate_captures
from .config import ScoringConfig
from .models import CategoryScore, PrimieraScore, PrimieraValue


def calculate_primiera(cards: tuple[Card, ...], config: ScoringConfig | None = None) -> PrimieraValue:
    config = config or ScoringConfig()
    cards = validate_unique(cards)
    Deck.create(config.deck_config).remove_known(cards)
    values = dict(config.primiera_values)
    best = []
    missing = []
    for suit in config.deck_config.suits:
        candidates = tuple(c for c in cards if c.suit == suit)
        if candidates:
            # Equal Primiera values use a stable card-id tie breaker.
            best.append(min(candidates, key=lambda c: (-values[c.rank], c.id)))
        else:
            missing.append(suit)
    return PrimieraValue(tuple(best), tuple(missing), sum(values[c.rank] for c in best))


def score_primiera(captures: CapturedCards, config: ScoringConfig | None = None) -> PrimieraScore:
    config = config or ScoringConfig()
    validate_captures(captures, config)
    player = calculate_primiera(captures.player, config)
    opponent = calculate_primiera(captures.opponent, config)
    if player.eligible and opponent.eligible:
        category = compare(player.value, opponent.value, config.primiera_points)
    else:
        winner = Player.PLAYER if player.eligible else Player.OPPONENT if opponent.eligible else None
        category = CategoryScore(player.value, opponent.value, winner,
                                 PlayerCounts(config.primiera_points if winner == Player.PLAYER else 0,
                                              config.primiera_points if winner == Player.OPPONENT else 0))
    return PrimieraScore(player, opponent, category)
