from collections import defaultdict
from dataclasses import replace
from fractions import Fraction

from engine.game_state import GameState, Player
from engine.moves import Move
from engine.opponent_model import OpponentModel, UniformOpponent
from engine.probabilities import PossibleWorld, ProbabilityDistribution, ProbabilityEngine
from engine.rules import RulesEngine
from .beliefs import SearchLimitExceeded, after_player_move, deal_hidden_opponent, rebase
from .config import SearchConfig
from .evaluation import PositionEvaluator
from .models import EdgeKind, NodeKind, SearchResult, TreeNode


class GameTree:
    def __init__(self, config: SearchConfig | None = None, *, rules: RulesEngine | None = None,
                 probabilities: ProbabilityEngine | None = None, opponent: OpponentModel | None = None,
                 evaluator: PositionEvaluator | None = None):
        self.config = config or SearchConfig()
        self.rules = rules or RulesEngine()
        self.probabilities = probabilities or ProbabilityEngine()
        self.opponent = opponent or UniformOpponent()
        self.evaluator = evaluator or PositionEvaluator()
        if self.rules.config.scopa_points != self.evaluator.scoring.config.scopa_points:
            raise ValueError("Rules and scoring Scopa point values must match")

    def search(self, state: GameState, belief: ProbabilityDistribution | None = None) -> SearchResult:
        belief = belief or self.probabilities.distribution(state,self.config.probability_method)
        if belief.state != self.probabilities.state(state):
            raise ValueError("Supplied belief does not match state")
        if len(belief.worlds)>self.config.max_belief_worlds:
            raise SearchLimitExceeded("Initial belief world limit exceeded")
        nodes: list[TreeNode] = []
        self._visit(nodes,state,belief,0,Fraction(1),None,None,EdgeKind.ROOT)
        return SearchResult(tuple(nodes),self.config.max_depth,max(n.depth for n in nodes),
                            belief.method,belief.seed,belief.sample_count)

    def _visit(self,nodes,state,belief,depth,probability,parent,branch,edge,move=None,drawn=None,pending=None):
        if len(nodes)>=self.config.max_nodes:
            raise SearchLimitExceeded(f"Search exceeds {self.config.max_nodes} nodes")
        evaluation=self.evaluator.evaluate(state)
        empty_hands=not state.player_hand and state.opponent_hand_size==0
        if pending is None and empty_hands and state.draw_pile_size:
            batch=min(self.config.cards_per_hand,state.draw_pile_size//2)
            if not batch or state.draw_pile_size%2:
                raise ValueError("Equal two-player dealing requires a positive even draw-pile size")
            pending=(batch,batch)
        reason=None
        if pending is not None:
            kind=NodeKind.CHANCE
        elif self.rules.round_finished(state):
            kind=NodeKind.TERMINAL
            reason="round_complete" if evaluation.source=="terminal_score" else "partial_round_complete"
        elif depth>=self.config.max_depth:
            kind=NodeKind.CUTOFF
            reason="depth_limit"
        elif (state.current_player==Player.PLAYER and not state.player_hand
              or state.current_player==Player.OPPONENT and not state.opponent_hand_size):
            raise ValueError("Acting hand is empty while the other hand is nonempty")
        else:
            kind=NodeKind.PLAYER if state.current_player==Player.PLAYER else NodeKind.OPPONENT
        node_id=len(nodes)
        nodes.append(TreeNode(node_id,parent,state,belief,depth,probability,branch,edge,kind,evaluation,evaluation.total,
                              move,drawn,stop_reason=reason))
        children=[]
        if kind==NodeKind.PLAYER:
            for action in self.rules.get_legal_moves(state):
                successor=action.resulting_state
                posterior=after_player_move(successor,belief,self.config.max_belief_worlds)
                children.append(self._visit(nodes,successor,posterior,depth+1,probability,node_id,None,
                                            EdgeKind.PLAYER_MOVE,move=action))
        elif kind==NodeKind.OPPONENT:
            for action,weight,successor,posterior in self._opponent_branches(state,belief):
                children.append(self._visit(nodes,successor,posterior,depth+1,probability*weight,node_id,weight,
                                            EdgeKind.OPPONENT_MOVE,move=action))
        elif kind==NodeKind.CHANCE:
            for card,weight,successor,posterior,next_pending in self._draw_branches(state,belief,pending):
                children.append(self._visit(nodes,successor,posterior,depth,probability*weight,node_id,weight,
                                            EdgeKind.UNKNOWN_CARD,drawn=card,pending=next_pending))
        if children:
            if kind==NodeKind.PLAYER:
                value=max(nodes[i].value for i in children)
            else:
                if sum((nodes[i].branch_probability for i in children),Fraction())!=1:
                    raise ValueError("Stochastic branch probabilities do not normalize")
                value=sum((nodes[i].branch_probability*nodes[i].value for i in children),Fraction())
            nodes[node_id]=replace(nodes[node_id],children=tuple(children),value=value)
        return node_id

    def _opponent_branches(self,state,belief):
        groups={}
        for item in belief.worlds:
            concrete=state.evolve(opponent_known_cards=item.world.opponent_hand)
            moves=self.rules.get_legal_moves(concrete)
            weights=self.opponent.probabilities(concrete,moves)
            if (len(weights)!=len(moves) or any(not isinstance(p,Fraction) or p<0 for p in weights)
                    or sum(weights,Fraction())!=1):
                raise ValueError("Opponent model must supply normalized nonnegative Fraction weights")
            for action,likelihood in zip(moves,weights,strict=True):
                if not likelihood:
                    continue
                key=(action.played_card,action.captured_cards)
                if key not in groups:
                    groups[key]=defaultdict(Fraction)
                successor_world=PossibleWorld(tuple(c for c in item.world.opponent_hand if c!=action.played_card),
                                              item.world.draw_pile,item.world.unassigned)
                groups[key][successor_world]+=item.probability*likelihood
        for (card,captured),weights in sorted(groups.items(),key=lambda item:(item[0][0].id,tuple(c.id for c in item[0][1]))):
            action=self.rules.evaluate_move(state,Move(card,captured,Player.OPPONENT))
            weight=sum(weights.values(),Fraction())
            posterior=rebase(action.resulting_state,belief,weights,self.config.max_belief_worlds)
            yield action,weight,action.resulting_state,posterior

    def _draw_branches(self,state,belief,pending):
        remaining,opponent_count=pending
        groups={}
        for item in belief.worlds:
            for card in item.world.draw_pile:
                if card not in groups:
                    groups[card]=defaultdict(Fraction)
                successor_world=PossibleWorld(item.world.opponent_hand,
                    tuple(c for c in item.world.draw_pile if c!=card),item.world.unassigned)
                groups[card][successor_world]+=item.probability/Fraction(len(item.world.draw_pile))
        for card,weights in sorted(groups.items(),key=lambda item:item[0].id):
            weight=sum(weights.values(),Fraction())
            successor=state.evolve(player_hand=state.player_hand+(card,),draw_pile_size=state.draw_pile_size-1)
            if remaining>1:
                posterior=rebase(successor,belief,weights,self.config.max_belief_worlds)
                next_pending=(remaining-1,opponent_count)
            else:
                # Opponent receives hidden cards. Aggregate these assignments instead of revealing them.
                successor=successor.evolve(opponent_hand_size=opponent_count,
                    draw_pile_size=successor.draw_pile_size-opponent_count,current_player=self.config.first_player)
                posterior=deal_hidden_opponent(successor,belief,weights,opponent_count,self.config.max_belief_worlds)
                next_pending=None
            yield card,weight,successor,posterior,next_pending
