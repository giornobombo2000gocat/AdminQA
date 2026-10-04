from dataclasses import dataclass
from fractions import Fraction

from engine.game_state import GameState
from engine.scoring import IncompleteRound, ScoringEngine


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    captured_cards: Fraction = Fraction(1)
    scopa: Fraction = Fraction(1)
    denari: Fraction = Fraction(1)
    sette_bello: Fraction = Fraction(1)
    primiera: Fraction = Fraction(1)
    previous_score: Fraction = Fraction(1)

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int and not isinstance(value, Fraction):
                raise ValueError("Evaluation weights must be integers or Fractions")
            if value < 0:
                raise ValueError("Evaluation weights must be nonnegative")
            object.__setattr__(self, name, Fraction(value))


@dataclass(frozen=True, slots=True)
class PositionEvaluation:
    source: str
    captured_cards: Fraction
    scopa: Fraction
    denari: Fraction
    sette_bello: Fraction
    primiera: Fraction
    previous_score: Fraction

    @property
    def total(self) -> Fraction:
        return self.captured_cards + self.scopa + self.denari + self.sette_bello + self.primiera + self.previous_score


class PositionEvaluator:
    """Deterministic heuristic at cutoffs; category score at settled complete rounds."""

    def __init__(self, scoring: ScoringEngine | None = None, config: EvaluationConfig | None = None):
        self.scoring = scoring or ScoringEngine()
        self.config = config or EvaluationConfig()

    def evaluate(self, state: GameState) -> PositionEvaluation:
        player, opponent = self.evaluate_sides(state)
        return PositionEvaluation(player.source,
            player.captured_cards-opponent.captured_cards,
            player.scopa-opponent.scopa, player.denari-opponent.denari,
            player.sette_bello-opponent.sette_bello, player.primiera-opponent.primiera,
            player.previous_score-opponent.previous_score)

    def evaluate_sides(self, state: GameState) -> tuple[PositionEvaluation, PositionEvaluation]:
        """Separate side utilities whose difference is the position evaluation."""
        try:
            final = self.scoring.calculate_score(state)
        except IncompleteRound:
            final = None
        b = final.breakdown if final else self.scoring.evaluate_captures(state.captured_cards, state.scopa_count)
        w = self.config
        results=[]
        for side in ("player", "opponent"):
            if final:
                cards=Fraction(getattr(b.captured_cards.points,side))
                denari=Fraction(getattr(b.denari.points,side))
                primiera=Fraction(getattr(b.primiera.category.points,side))
            else:
                cards=Fraction(getattr(b.captured_cards,f"{side}_value"),len(state.deck.cards))
                denari_size=sum(c.suit==self.scoring.config.denari_suit for c in state.deck.cards)
                denari=Fraction(getattr(b.denari,f"{side}_value"),denari_size)
                max_prime=len(self.scoring.config.deck_config.suits)*max(dict(self.scoring.config.primiera_values).values())
                primiera=Fraction(getattr(b.primiera,side).value,max_prime)
            results.append(PositionEvaluation("terminal_score" if final else "heuristic",
                cards*w.captured_cards, Fraction(getattr(b.scopa.points,side))*w.scopa, denari*w.denari,
                Fraction(getattr(b.sette_bello.points,side))*w.sette_bello,primiera*w.primiera,
                Fraction(getattr(state,f"{side}_score"))*w.previous_score))
        return results[0],results[1]
