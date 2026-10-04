from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path

from .models import SimulationComparison, SimulationResult


def save_simulation(result: SimulationResult | SimulationComparison,path: str | Path, *,include_runtime: bool=False) -> None:
    data=asdict(result)
    runtime=data["simulation"] if isinstance(result,SimulationComparison) else data
    if not include_runtime:
        for key in ("workers","chunk_size","calculation_time"):
            runtime.pop(key,None)
    def encode(value):
        if isinstance(value,Fraction):
            return {"numerator":value.numerator,"denominator":value.denominator}
        raise TypeError(f"Cannot encode {type(value).__name__}")
    Path(path).write_text(json.dumps(data,default=encode,ensure_ascii=False,indent=2),encoding="utf-8")
