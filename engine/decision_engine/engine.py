from fractions import Fraction
from time import perf_counter

from engine.game_state import GameState, Player
from engine.game_tree import GameTree, NodeKind, PositionEvaluation, PositionEvaluator
from engine.opponent_model import OpponentModel
from engine.probabilities import ProbabilityEngine
from engine.rules import RulesEngine
from engine.scoring import ScoringEngine
from .config import DecisionConfig
from .models import AnalysisResult, MoveAnalysis, OutcomeEvaluation


def move_key(move):
    return move.played_card.id, tuple(sorted(c.id for c in move.captured_cards))


class DecisionEngine:
    """Compare every legal player move using one shared belief-state search."""

    def __init__(self, config: DecisionConfig | None = None, *, rules: RulesEngine | None = None,
                 scoring: ScoringEngine | None = None, opponent: OpponentModel | None = None):
        self.config=config or DecisionConfig()
        self.tree=GameTree(self.config.search,rules=rules,
            probabilities=ProbabilityEngine(self.config.probabilities),opponent=opponent,
            evaluator=PositionEvaluator(scoring=scoring,config=self.config.evaluation))

    def analyze(self,state: GameState) -> AnalysisResult:
        start=perf_counter()
        if not isinstance(state,GameState):
            raise TypeError("Input must be GameState")
        if state.current_player!=Player.PLAYER:
            raise ValueError("DecisionEngine analyzes the player's turn, not an opponent turn")
        legal=self.tree.rules.get_legal_moves(state)
        if not legal:
            status="round_finished" if self.tree.rules.round_finished(state) else "no_legal_moves"
            return AnalysisResult((),None,None,None,self.config.search.max_depth,0,status,perf_counter()-start)
        tree=self.tree.search(state)
        nodes=tree.explored_states
        root_moves=tuple(nodes[i].move for i in tree.root.children)
        if {move_key(m) for m in root_moves}!={move_key(m) for m in legal} or len(root_moves)!=len(legal):
            raise ValueError("Search did not cover every legal root action")
        cache={}

        def leaves(node_id,weight=Fraction(1)):
            node=nodes[node_id]
            if not node.children:
                yield node_id,weight
            elif node.kind==NodeKind.PLAYER:
                chosen=min(node.children,key=lambda i:(-nodes[i].value,move_key(nodes[i].move)))
                yield from leaves(chosen,weight)
            else:
                for child_id in node.children:
                    yield from leaves(child_id,weight*nodes[child_id].branch_probability)

        def leaf_metrics(node_id):
            if node_id not in cache:
                leaf=nodes[node_id]
                side_values=self.tree.evaluator.evaluate_sides(leaf.state)
                breakdown=self.tree.evaluator.scoring.evaluate_captures(leaf.state.captured_cards,leaf.state.scopa_count)
                cache[node_id]=(leaf,side_values,breakdown)
            return cache[node_id]

        analyses=[]
        components=("captured_cards","scopa","denari","sette_bello","primiera","previous_score")
        for node_id in tree.root.children:
            node=nodes[node_id]
            outcomes=[]
            for leaf_id,probability in leaves(node_id):
                leaf,(player,opponent),b=leaf_metrics(leaf_id)
                outcomes.append(OutcomeEvaluation(leaf_id,probability,player,opponent,
                    leaf.state.scopa_count.player-state.scopa_count.player,
                    leaf.state.scopa_count.opponent-state.scopa_count.opponent,
                    b.primiera.player.value,b.primiera.opponent.value,b.primiera.player.eligible,b.primiera.opponent.eligible,
                    bool(b.sette_bello.player_value),bool(b.sette_bello.opponent_value),
                    b.sette_bello.points.player,b.sette_bello.points.opponent,
                    b.captured_cards.player_value,b.captured_cards.opponent_value))
            outcomes=tuple(outcomes)
            if sum((o.probability for o in outcomes),Fraction())!=1:
                raise ValueError("Move outcome probabilities must sum to one")
            def expected(fn):
                return sum((o.probability*fn(o) for o in outcomes),Fraction())
            sources={o.player_evaluation.source for o in outcomes}
            source="expected_terminal_score" if sources=={"terminal_score"} else "expected_heuristic" if sources=={"heuristic"} else "expected_mixed"
            expected_eval=PositionEvaluation(source,*(expected(lambda o,name=name:
                getattr(o.player_evaluation,name)-getattr(o.opponent_evaluation,name)) for name in components))
            player_value=expected(lambda o:o.player_evaluation.total)
            opponent_value=expected(lambda o:o.opponent_evaluation.total)
            if expected_eval.total!=node.value or player_value-opponent_value!=node.value:
                raise ValueError("Outcome aggregation disagrees with game-tree expected value")
            analyses.append(MoveAnalysis(node.move,node_id,node.evaluation,expected_eval,node.value,player_value,opponent_value,
                expected(lambda o:int(o.player_scopa_delta>0)),expected(lambda o:int(o.opponent_scopa_delta>0)),
                expected(lambda o:o.player_scopa_delta),expected(lambda o:o.primiera_value),
                expected(lambda o:o.opponent_primiera_value),expected(lambda o:int(o.primiera_eligible)),
                expected(lambda o:o.sette_bello_points),expected(lambda o:int(o.sette_bello_owned)),
                expected(lambda o:o.captured_cards),expected(lambda o:int(o.player_evaluation.source=="terminal_score")),outcomes))
        analyses=tuple(sorted(analyses,key=lambda item:move_key(item.move)))
        recommended=min(analyses,key=lambda item:(-item.expected_value,move_key(item.move)))
        return AnalysisResult(analyses,recommended.move,tree,tree.root.belief,self.config.search.max_depth,
                              tree.reached_depth,"analyzed",perf_counter()-start)
