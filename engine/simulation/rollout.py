from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from random import Random

from engine.game_state import GameState, Player
from engine.game_tree import PositionEvaluator
from engine.moves import Move
from engine.probabilities import ProbabilityState
from engine.rules import RulesEngine
from engine.scoring import ScoringEngine
from .config import SimulationConfig
from .models import RolloutTrace, SimulationEvent

METRICS=("expected_value","player_expected_value","opponent_expected_value","primiera_value",
         "opponent_primiera_value","captured_cards","opponent_captured_cards","new_scopa_count","sette_bello_value")
EVENTS=("player_scopa","opponent_scopa","sette_bello","terminal")


def iteration_seed(seed: int,index: int) -> int:
    return int.from_bytes(sha256(f"scopa-simulation-v1:{seed}:{index}".encode("ascii")).digest(),"big")


def action_key(move: Move):
    return move.played_card.id,tuple(sorted(c.id for c in move.captured_cards))


def player_action(moves: tuple[Move,...],evaluator: PositionEvaluator,policy: str) -> Move:
    if policy=="first_legal":
        return min(moves,key=action_key)
    return min(moves,key=lambda move:(-evaluator.evaluate(move.resulting_state).total,action_key(move)))


def metrics(state: GameState,initial: GameState,evaluator: PositionEvaluator):
    player,opponent=evaluator.evaluate_sides(state)
    b=evaluator.scoring.evaluate_captures(state.captured_cards,state.scopa_count)
    values=(player.total-opponent.total,player.total,opponent.total,Fraction(b.primiera.player.value),
            Fraction(b.primiera.opponent.value),Fraction(b.captured_cards.player_value),Fraction(b.captured_cards.opponent_value),
            Fraction(state.scopa_count.player-initial.scopa_count.player),Fraction(b.sette_bello.points.player))
    events=(state.scopa_count.player>initial.scopa_count.player,state.scopa_count.opponent>initial.scopa_count.opponent,
            bool(b.sette_bello.player_value),player.source=="terminal_score")
    return values,events,player.source


def rollout(initial: GameState,belief: ProbabilityState,config: SimulationConfig,index: int,
            forced: Move | None,rules: RulesEngine,evaluator: PositionEvaluator):
    rng=Random(iteration_seed(config.seed,index))
    selected=rng.sample(belief.unknown_cards,belief.hidden_opponent_count+belief.draw_pile_size)
    private_hand=tuple(sorted(belief.opponent_known_cards+tuple(selected[:belief.hidden_opponent_count]),key=lambda c:c.id))
    private_draw=tuple(selected[belief.hidden_opponent_count:])
    state=initial
    depth=0
    trace=[]
    record=index<config.trace_limit
    while True:
        # Complete a batch before returning a cutoff, matching GameTree depth semantics.
        if not state.player_hand and state.opponent_hand_size==0 and state.draw_pile_size:
            count=min(config.cards_per_hand,state.draw_pile_size//2)
            if not count or state.draw_pile_size%2:
                raise ValueError("Equal dealing requires a positive even draw-pile size")
            drawn=private_draw[:count]
            private_hand=tuple(sorted(private_draw[count:2*count],key=lambda c:c.id))
            private_draw=private_draw[2*count:]
            state=state.evolve(player_hand=drawn,opponent_known_cards=(),opponent_hand_size=count,
                               draw_pile_size=len(private_draw),current_player=config.first_player)
            if record:
                trace.append(SimulationEvent("deal",player_drawn_cards=drawn))
        if rules.round_finished(state) or depth>=config.max_depth:
            break
        if state.current_player==Player.PLAYER:
            moves=rules.get_legal_moves(state)
            if not moves:
                raise ValueError("Acting player hand is empty while opponent hand is nonempty")
            action=forced if depth==0 and forced is not None else player_action(moves,evaluator,config.player_policy)
        else:
            if not private_hand:
                raise ValueError("Acting opponent hand is empty while player hand is nonempty")
            concrete=state.evolve(opponent_known_cards=private_hand)
            moves=rules.get_legal_moves(concrete)
            chosen=moves[rng.randrange(len(moves))]  # A sample from the explicitly uniform opponent policy.
            action=Move(chosen.played_card,chosen.captured_cards,Player.OPPONENT)
        # Only the played opponent card becomes observable; the full private hand never leaks.
        action=rules.evaluate_move(state,action)
        state=action.resulting_state
        if action.actor==Player.OPPONENT:
            private_hand=tuple(c for c in private_hand if c!=action.played_card)
        if record:
            trace.append(SimulationEvent("move",move=action))
        depth+=1
    values,events,source=metrics(state,initial,evaluator)
    saved=RolloutTrace(index,state,depth,source,tuple(trace)) if record else None
    return values,events,depth,saved


@dataclass(frozen=True, slots=True)
class BatchJob:
    initial: GameState
    belief: ProbabilityState
    config: SimulationConfig
    start: int
    stop: int
    forced: Move | None


@dataclass(frozen=True, slots=True)
class BatchResult:
    count: int
    totals: tuple[Fraction,...]
    squares: tuple[Fraction,...]
    successes: tuple[int,...]
    reached_depth: int
    traces: tuple[RolloutTrace,...]


def run_batch(job: BatchJob) -> BatchResult:
    rules=RulesEngine(job.config.rules)
    evaluator=PositionEvaluator(ScoringEngine(job.config.scoring),job.config.evaluation)
    # Immutable keys; reuse pure calculations, never RNG draws or sampled outcomes.
    # Caches are bounded and local to this batch, then discarded with its engines.
    rules.get_legal_moves=lru_cache(maxsize=256)(rules.get_legal_moves)
    rules.evaluate_move=lru_cache(maxsize=256)(rules.evaluate_move)
    evaluator.evaluate=lru_cache(maxsize=256)(evaluator.evaluate)
    evaluator.evaluate_sides=lru_cache(maxsize=256)(evaluator.evaluate_sides)
    evaluator.scoring.evaluate_captures=lru_cache(maxsize=256)(evaluator.scoring.evaluate_captures)
    totals=[Fraction() for _ in METRICS]
    squares=[Fraction() for _ in METRICS]
    successes=[0 for _ in EVENTS]
    reached=0
    traces=[]
    for index in range(job.start,job.stop):
        values,events,depth,trace=rollout(job.initial,job.belief,job.config,index,job.forced,rules,evaluator)
        for i,value in enumerate(values):
            totals[i]+=value
            squares[i]+=value*value
        for i,event in enumerate(events):
            successes[i]+=int(event)
        reached=max(reached,depth)
        if trace is not None:
            traces.append(trace)
    return BatchResult(job.stop-job.start,tuple(totals),tuple(squares),tuple(successes),reached,tuple(traces))
