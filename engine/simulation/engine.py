from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from multiprocessing import get_context
from time import perf_counter

from engine.game_state import GameState, Player
from engine.game_tree import GameTree, NodeKind, PositionEvaluator, SearchConfig
from engine.moves import Move
from engine.probabilities import ProbabilityConfig, ProbabilityEngine, ProbabilityState
from engine.rules import RulesEngine
from engine.scoring import ScoringEngine
from .config import SimulationConfig
from .models import (ComparisonMetric, ExactSimulationResult, SimulationComparison, SimulationResult)
from .rollout import BatchJob, EVENTS, METRICS, action_key, metrics, run_batch
from .statistics import mean_estimate, proportion_estimate


class SimulationEngine:
    def __init__(self,config: SimulationConfig | None=None):
        self.config=config or SimulationConfig()
        self.rules=RulesEngine(self.config.rules)
        self.evaluator=PositionEvaluator(ScoringEngine(self.config.scoring),self.config.evaluation)

    def _validate(self,state,move):
        if not isinstance(state,GameState):
            raise TypeError("Input must be GameState")
        self.evaluator.evaluate(state)  # Validate scoring/deck compatibility before spawning workers.
        if move is not None:
            if not isinstance(move,Move):
                raise TypeError("Expected Move")
            if self.config.max_depth<1 or state.current_player!=Player.PLAYER:
                raise ValueError("Forced player action requires player turn and depth >=1")
            self.rules.evaluate_move(state,move)
        return ProbabilityState.from_game_state(state)

    def _bounds(self,state):
        w=self.config.evaluation
        scoring=self.config.scoring
        def utility(side):
            minimum=Fraction(getattr(state,f"{side}_score"))*w.previous_score+Fraction(getattr(state.scopa_count,side)*scoring.scopa_points)*w.scopa
            maximum=minimum+self.config.max_depth*scoring.scopa_points*w.scopa
            maximum+=max(1,scoring.captured_cards_points)*w.captured_cards+max(1,scoring.denari_points)*w.denari
            maximum+=scoring.sette_bello_points*w.sette_bello+max(1,scoring.primiera_points)*w.primiera
            return minimum,maximum
        p_low,p_high=utility("player")
        o_low,o_high=utility("opponent")
        max_prime=len(scoring.deck_config.suits)*max(dict(scoring.primiera_values).values())
        deck_size=len(state.deck.cards)
        return ((p_low-o_high,p_high-o_low),(p_low,p_high),(o_low,o_high),
                (Fraction(),Fraction(max_prime)),(Fraction(),Fraction(max_prime)),
                (Fraction(),Fraction(deck_size)),(Fraction(),Fraction(deck_size)),
                (Fraction(),Fraction(self.config.max_depth)),(Fraction(),Fraction(scoring.sette_bello_points)))

    def simulate(self,state: GameState,move: Move | None=None) -> SimulationResult:
        start=perf_counter()
        belief=self._validate(state,move)
        config=self.config
        jobs=tuple(BatchJob(state,belief,config,i,min(i+config.chunk_size,config.iterations),move)
                   for i in range(0,config.iterations,config.chunk_size))
        if config.workers==1:
            batches=tuple(run_batch(job) for job in jobs)
        else:
            # spawn works on Windows and avoids inheriting global RNG or forked application state.
            with ProcessPoolExecutor(max_workers=config.workers,mp_context=get_context("spawn")) as pool:
                batches=tuple(pool.map(run_batch,jobs))
        count=sum(batch.count for batch in batches)
        if count!=config.iterations:
            raise ValueError("Incomplete simulation; no partial result is accepted")
        bounds=self._bounds(state)
        means=tuple(mean_estimate(name,count,
            sum((batch.totals[i] for batch in batches),Fraction()),
            sum((batch.squares[i] for batch in batches),Fraction()),bounds[i],config.confidence)
            for i,name in enumerate(METRICS))
        proportions=tuple(proportion_estimate(name,count,sum(batch.successes[i] for batch in batches),config.confidence)
                          for i,name in enumerate(EVENTS))
        traces=tuple(sorted((trace for batch in batches for trace in batch.traces),key=lambda trace:trace.iteration))
        return SimulationResult(count,config.seed,config.max_depth,max(batch.reached_depth for batch in batches),
                                config.player_policy,means,proportions,traces,config.workers,config.chunk_size,perf_counter()-start)

    def exact_reference(self,state: GameState,move: Move | None=None) -> ExactSimulationResult:
        self._validate(state,move)
        config=self.config
        tree=GameTree(SearchConfig(max_depth=config.max_depth,max_nodes=config.max_exact_nodes,
            max_belief_worlds=config.max_exact_worlds,cards_per_hand=config.cards_per_hand,
            first_player=config.first_player,probability_method="exact"),rules=self.rules,evaluator=self.evaluator,
            probabilities=ProbabilityEngine(ProbabilityConfig(max_exact_worlds=config.max_exact_worlds)))
        search=tree.search(state)
        totals=[Fraction() for _ in METRICS]
        events=[Fraction() for _ in EVENTS]
        mass=Fraction()
        def visit(node_id,weight):
            nonlocal mass
            node=search.explored_states[node_id]
            if not node.children:
                values,flags,_=metrics(node.state,state,self.evaluator)
                for i,value in enumerate(values):
                    totals[i]+=weight*value
                for i,flag in enumerate(flags):
                    events[i]+=weight*int(flag)
                mass+=weight
            elif node.kind==NodeKind.PLAYER:
                if node_id==0 and move is not None:
                    selected=next(i for i in node.children if action_key(search.explored_states[i].move)==action_key(move))
                elif config.player_policy=="first_legal":
                    selected=min(node.children,key=lambda i:action_key(search.explored_states[i].move))
                else:
                    selected=min(node.children,key=lambda i:(-search.explored_states[i].evaluation.total,
                                                             action_key(search.explored_states[i].move)))
                visit(selected,weight)
            else:
                for child in node.children:
                    visit(child,weight*search.explored_states[child].branch_probability)
        visit(0,Fraction(1))
        if mass!=1:
            raise ValueError("Exact reference mass must be one")
        return ExactSimulationResult(tuple(zip(METRICS,totals,strict=True)),tuple(zip(EVENTS,events,strict=True)),search.node_count)

    def compare_exact(self,state: GameState,move: Move | None=None) -> SimulationComparison:
        exact=self.exact_reference(state,move)
        simulation=self.simulate(state,move)
        comparisons=[]
        for name,value in exact.metrics:
            estimate=simulation.metric(name)
            interval=estimate.confidence_interval
            comparisons.append(ComparisonMetric(name,value,estimate.mean,abs(value-estimate.mean),interval,
                interval[0]<=float(value)<=interval[1] if interval is not None else None))
        for name,value in exact.probabilities:
            estimate=simulation.event(name)
            interval=estimate.confidence_interval
            comparisons.append(ComparisonMetric(name,value,estimate.probability,abs(value-estimate.probability),interval,
                                               interval[0]<=float(value)<=interval[1]))
        return SimulationComparison(exact,simulation,tuple(comparisons))
