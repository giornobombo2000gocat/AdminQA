from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path

from .models import AnalysisResult


def save_analysis(result: AnalysisResult,path: str | Path, *, include_timing: bool=False) -> None:
    """Deterministic mathematical report; wall-clock timing is optional metadata."""
    def action(move):
        return {"played_card":move.played_card.id,"captured_cards":[c.id for c in move.captured_cards],
                "creates_scopa":move.creates_scopa,"resulting_table":[c.id for c in move.resulting_state.table_cards]}
    moves=[]
    for item in result.all_moves:
        data=asdict(item)
        data["move"]=action(item.move)
        moves.append(data)
    data={"status":result.status,"search_depth":result.search_depth,"reached_depth":result.reached_depth,
          "probability_method":result.probabilities.method if result.probabilities else None,
          "seed":result.probabilities.seed if result.probabilities else None,
          "sample_count":result.probabilities.sample_count if result.probabilities else None,
          "recommended_move":action(result.recommended_move) if result.recommended_move else None,
          "expected_value":result.expected_value,"scopa_probability":result.scopa_probability,
          "primiera_value":result.primiera_value,"sette_bello_value":result.sette_bello_value,
          "opponent_expected_value":result.opponent_expected_value,"all_moves":moves}
    if include_timing:
        data["calculation_time_seconds"]=result.calculation_time
    def encode(value):
        if isinstance(value,Fraction):
            return {"numerator":value.numerator,"denominator":value.denominator}
        raise TypeError(f"Cannot encode {type(value).__name__}")
    Path(path).write_text(json.dumps(data,default=encode,ensure_ascii=False,indent=2),encoding="utf-8")
