from dataclasses import replace

from engine.cards import Card, validate_unique
from engine.combinations import sum_combinations
from engine.game_state import CapturedCards, GameState, HistoryEntry, Player, PlayerCounts
from engine.moves import CaptureType, Move
from .config import RulesConfig


class IllegalMove(ValueError):
    """Move violates rules or the supplied observation."""


class IncompleteInformation(ValueError):
    """An exhaustive action set or terminal transition needs missing information."""


class RulesEngine:
    def __init__(self, config: RulesConfig | None = None):
        self.config = config or RulesConfig()

    def get_captures(self, played_card: Card, table_cards: tuple[Card, ...]) -> tuple[tuple[Card, ...], ...]:
        table_cards = validate_unique(table_cards)
        validate_unique((played_card,) + table_cards)
        singles = tuple((c,) for c in sorted(table_cards, key=lambda c: c.id) if c.value == played_card.value)
        if singles and self.config.single_card_priority:
            return singles
        return sum_combinations(table_cards, played_card.value)

    def can_capture(self, played_card: Card, table_cards: tuple[Card, ...]) -> bool:
        return bool(self.get_captures(played_card, table_cards))

    @staticmethod
    def round_finished(state: GameState) -> bool:
        return not state.player_hand and state.opponent_hand_size == 0 and state.draw_pile_size == 0

    def _final_play(self, state: GameState) -> bool:
        return state.draw_pile_size == 0 and len(state.player_hand) + state.opponent_hand_size == 1

    def is_scopa(self, state: GameState, move: Move) -> bool:
        try:
            self._validate_move(state, move)
        except ValueError:
            return False
        captures = self.get_captures(move.played_card, state.table_cards)
        ids = {c.id for c in move.captured_cards}
        legal = any(set(capture) == set(move.captured_cards) for capture in captures)
        return (legal and bool(ids) and ids == {c.id for c in state.table_cards}
                and (self.config.final_play_scopa or not self._final_play(state)))

    def evaluate_move(self, state: GameState, move: Move) -> Move:
        """Validate a proposed action and return all authoritative detection fields."""
        resulting_state = self.apply_move(state, move)
        captured = tuple(sorted(move.captured_cards, key=lambda c: c.id))
        scopa = self.is_scopa(state, move)
        return replace(move, captured_cards=captured,
                       capture_type=CaptureType.NONE if not captured else
                       CaptureType.SINGLE if len(captured) == 1 else CaptureType.SUM,
                       creates_scopa=scopa,
                       immediate_score=self.config.scopa_points if scopa else 0,
                       resulting_state=resulting_state)

    def get_legal_moves(self, state: GameState) -> tuple[Move, ...]:
        if self.round_finished(state):
            return ()
        if state.current_player == Player.OPPONENT and state.hidden_opponent_count:
            raise IncompleteInformation("Cannot enumerate an unknown opponent hand; reveal cards first")
        hand = state.player_hand if state.current_player == Player.PLAYER else state.opponent_known_cards
        moves = []
        for card in sorted(hand, key=lambda c: c.id):
            captures = self.get_captures(card, state.table_cards)
            options = captures if self.config.mandatory_capture and captures else captures + ((),)
            for captured in options:
                move = Move(card, captured, state.current_player)
                moves.append(self.evaluate_move(state, move))
        return tuple(moves)

    def _validate_move(self, state: GameState, move: Move) -> None:
        if move.actor != state.current_player:
            raise IllegalMove("Wrong actor")
        if self.round_finished(state):
            raise IllegalMove("Round already finished")
        card = move.played_card
        opponent = move.actor == Player.OPPONENT
        hand = state.opponent_known_cards if opponent else state.player_hand
        revealing = opponent and card not in hand
        if revealing:
            if not state.hidden_opponent_count or card not in state.unknown_cards:
                raise IllegalMove("Card is not in the opponent's possible hidden hand")
        elif card not in hand:
            raise IllegalMove("Card is not in the acting player's hand")
        captures = self.get_captures(card, state.table_cards)
        captured = move.captured_cards
        if captured:
            if not any(set(c) == set(captured) for c in captures):
                raise IllegalMove("Invalid capture or single-card priority violation")
        elif captures and self.config.mandatory_capture:
            raise IllegalMove("Capture is compulsory")

    def apply_move(self, state: GameState, move: Move) -> GameState:
        # Recompute all derived metadata; never trust client-supplied resulting_state/score.
        self._validate_move(state, move)
        card = move.played_card
        opponent = move.actor == Player.OPPONENT
        hand = state.opponent_known_cards if opponent else state.player_hand
        captured = move.captured_cards
        captured = tuple(sorted(captured, key=lambda c: c.id))
        table = tuple(c for c in state.table_cards if c not in captured) if captured else state.table_cards + (card,)
        own = state.captured_cards.player
        other = state.captured_cards.opponent
        last = move.actor if captured else state.last_capture_player
        if captured:
            if opponent:
                other += (card,) + captured
            else:
                own += (card,) + captured
        if self._final_play(state) and table:
            if last is None:
                raise IncompleteInformation("Final leftovers require the last capture owner")
            if last == Player.PLAYER:
                own += table
            else:
                other += table
            table = ()
        scopa = self.is_scopa(state, move)
        counts = PlayerCounts(state.scopa_count.player + int(scopa and not opponent),
                              state.scopa_count.opponent + int(scopa and opponent))
        return state.evolve(
            table_cards=table,
            player_hand=state.player_hand if opponent else tuple(c for c in hand if c != card),
            opponent_known_cards=tuple(c for c in hand if c != card) if opponent else state.opponent_known_cards,
            opponent_hand_size=state.opponent_hand_size - int(opponent),
            played_cards=state.played_cards + (card,), captured_cards=CapturedCards(own, other),
            current_player=Player.PLAYER if opponent else Player.OPPONENT,
            turn_number=state.turn_number + 1, scopa_count=counts, last_capture_player=last,
            game_history=state.game_history + (HistoryEntry(state.turn_number + 1, move.actor, card, captured),),
        )
