from dataclasses import dataclass

from engine.cards import Card
from engine.game_state import Player, PlayerCounts


@dataclass(frozen=True, slots=True)
class CategoryScore:
    player_value: int
    opponent_value: int
    winner: Player | None
    points: PlayerCounts


@dataclass(frozen=True, slots=True)
class ScopaScore:
    counts: PlayerCounts
    points: PlayerCounts


@dataclass(frozen=True, slots=True)
class PrimieraValue:
    best_cards: tuple[Card, ...]
    missing_suits: tuple[str, ...]
    value: int

    @property
    def eligible(self) -> bool:
        return not self.missing_suits


@dataclass(frozen=True, slots=True)
class PrimieraScore:
    player: PrimieraValue
    opponent: PrimieraValue
    category: CategoryScore


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    captured_cards: CategoryScore
    scopa: ScopaScore
    denari: CategoryScore
    sette_bello: CategoryScore
    primiera: PrimieraScore

    @property
    def round_points(self) -> PlayerCounts:
        categories = (self.captured_cards, self.scopa, self.denari, self.sette_bello, self.primiera.category)
        return PlayerCounts(sum(c.points.player for c in categories), sum(c.points.opponent for c in categories))


@dataclass(frozen=True, slots=True)
class FinalScore:
    breakdown: ScoreBreakdown
    previous_scores: PlayerCounts

    @property
    def round_points(self) -> PlayerCounts:
        return self.breakdown.round_points

    @property
    def total_scores(self) -> PlayerCounts:
        return PlayerCounts(self.previous_scores.player + self.round_points.player,
                            self.previous_scores.opponent + self.round_points.opponent)
