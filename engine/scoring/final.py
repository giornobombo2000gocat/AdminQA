from engine.cards import Deck
from engine.game_state import CapturedCards, GameState, PlayerCounts
from .captured_cards import score_captured_cards
from .config import ScoringConfig
from .denari import score_denari
from .models import FinalScore, ScoreBreakdown
from .primiera import score_primiera
from .scopa import score_scopa
from .sette_bello import score_sette_bello


class IncompleteRound(ValueError):
    """Final scoring requires the complete settled round."""


class ScoringEngine:
    def __init__(self, config: ScoringConfig | None = None):
        self.config = config or ScoringConfig()

    def evaluate_captures(self, captures: CapturedCards, scopa_counts: PlayerCounts) -> ScoreBreakdown:
        """Current category standings; not an estimate of future or final points."""
        return ScoreBreakdown(score_captured_cards(captures, self.config),
                              score_scopa(scopa_counts, self.config),
                              score_denari(captures, self.config),
                              score_sette_bello(captures, self.config),
                              score_primiera(captures, self.config))

    def calculate_score(self, state: GameState) -> FinalScore:
        universe = set(Deck.create(self.config.deck_config).cards)
        if set(state.deck.cards) != universe:
            raise ValueError("State deck does not match scoring configuration")
        if (state.player_hand or state.opponent_hand_size or state.draw_pile_size or state.table_cards):
            raise IncompleteRound("Hands, draw pile and table must be empty")
        if set(state.captured_cards.player + state.captured_cards.opponent) != universe:
            raise IncompleteRound("All configured cards must belong to a capture pile")
        return FinalScore(self.evaluate_captures(state.captured_cards, state.scopa_count),
                          PlayerCounts(state.player_score, state.opponent_score))
