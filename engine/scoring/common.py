from engine.cards import Deck
from engine.game_state import CapturedCards, Player, PlayerCounts
from .config import ScoringConfig
from .models import CategoryScore


def validate_captures(captures: CapturedCards, config: ScoringConfig) -> None:
    if not isinstance(captures, CapturedCards):
        raise TypeError("Expected CapturedCards")
    Deck.create(config.deck_config).remove_known(captures.player + captures.opponent)


def compare(player_value: int, opponent_value: int, points: int) -> CategoryScore:
    winner = Player.PLAYER if player_value > opponent_value else Player.OPPONENT if opponent_value > player_value else None
    return CategoryScore(player_value, opponent_value, winner,
                         PlayerCounts(points if winner == Player.PLAYER else 0,
                                      points if winner == Player.OPPONENT else 0))
