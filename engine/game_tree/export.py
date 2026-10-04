from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path

from .models import SearchResult


def tree_to_dict(result: SearchResult) -> dict:
    nodes=[]
    for node in result.explored_states:
        action=None
        if node.move is not None:
            action={"played_card":node.move.played_card.id,
                    "captured_cards":[c.id for c in node.move.captured_cards],
                    "actor":node.move.actor.value,"capture_type":node.move.capture_type.value,
                    "creates_scopa":node.move.creates_scopa,"immediate_score":node.move.immediate_score}
        nodes.append({"id":node.id,"parent_id":node.parent_id,"children":list(node.children),
                      "kind":node.kind.value,"edge_kind":node.edge_kind.value,
                      "depth":node.depth,"probability":node.probability,
                      "branch_probability":node.branch_probability,"state":asdict(node.state),
                      "evaluation":asdict(node.evaluation),"evaluation_total":node.evaluation.total,
                      "value":node.value,"move":action,
                      "drawn_card":node.drawn_card.id if node.drawn_card else None,"stop_reason":node.stop_reason,
                      "belief":{"method":node.belief.method,"represented_worlds":len(node.belief.worlds),
                                "uniform_prior_world_count":node.belief.state.world_count,
                                "conditioned":node.belief.conditioned,"total_mass":node.belief.total_mass}})
    return {"search_depth":result.search_depth,"reached_depth":result.reached_depth,
            "node_count":result.node_count,"unique_state_count":result.unique_state_count,
            "probability_method":result.probability_method,"seed":result.seed,"sample_count":result.sample_count,
            "explored_states":nodes}


def save_tree(result: SearchResult, path: str | Path) -> None:
    """Export all observations and branch metadata; no hidden hand is published in state."""
    def encode(value):
        if isinstance(value,Fraction):
            return {"numerator":value.numerator,"denominator":value.denominator}
        raise TypeError(f"Cannot encode {type(value).__name__}")
    Path(path).write_text(json.dumps(tree_to_dict(result),default=encode,ensure_ascii=False,indent=2),encoding="utf-8")
