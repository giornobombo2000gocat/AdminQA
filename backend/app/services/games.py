from engine.decision_engine import DecisionConfig, DecisionEngine
from engine.game_tree import SearchConfig, SearchLimitExceeded
from engine.moves import Move
from engine.probabilities import EnumerationLimitExceeded, ProbabilityConfig
from engine.simulation import SimulationConfig, SimulationEngine

from backend.app.core.errors import AnalysisNotFound, CalculationLimitExceeded, InvalidEngineInput
from .repository import GameRepository
from .serialization import analysis_response, game_response, simulation_response, state_from_schema


class GameService:
    def __init__(self, repository: GameRepository):
        self.repository = repository

    @staticmethod
    def _engine_call(operation):
        try:
            return operation()
        except (SearchLimitExceeded, EnumerationLimitExceeded) as error:
            raise CalculationLimitExceeded(str(error)) from error
        except ValueError as error:
            raise InvalidEngineInput(str(error)) from error

    def create(self, request):
        state = self._engine_call(lambda: state_from_schema(request.state))
        return game_response(self.repository.create(state))

    def get(self, game_id):
        return game_response(self.repository.get(game_id))

    def update_state(self, game_id, request):
        self.repository.get(game_id)
        state = self._engine_call(lambda: state_from_schema(request.state))
        return game_response(self.repository.replace_state(game_id, state, request.expected_revision))

    def analyze(self, game_id, request):
        record = self.repository.get(game_id)
        def calculate():
            config = DecisionConfig(search=SearchConfig(max_depth=request.max_depth,
                max_nodes=request.max_nodes, max_belief_worlds=request.max_belief_worlds,
                cards_per_hand=request.cards_per_hand, first_player=request.first_player,
                probability_method=request.probability_method),
                probabilities=ProbabilityConfig(max_exact_worlds=request.max_exact_worlds,
                    monte_carlo_samples=request.monte_carlo_samples, seed=request.seed))
            return DecisionEngine(config).analyze(record.state)
        result = self._engine_call(calculate)
        saved = self.repository.save_analysis(game_id, record.revision, result)
        return analysis_response(saved)

    def get_analysis(self, game_id):
        record = self.repository.get(game_id)
        if record.analysis is None:
            raise AnalysisNotFound('No analysis for the current game state')
        return analysis_response(record)

    def simulate(self, game_id, request):
        record = self.repository.get(game_id)
        def calculate():
            move = None
            if request.move is not None:
                cards = {c.id: c for c in record.state.deck.cards}
                try:
                    move = Move(cards[request.move.played_card], tuple(cards[key] for key in request.move.captured_cards))
                except KeyError as error:
                    raise ValueError(f'Unknown card id: {error.args[0]}') from None
            config = SimulationConfig(**request.model_dump(exclude={'move'}))
            return SimulationEngine(config).simulate(record.state, move)
        result = self._engine_call(calculate)
        saved = self.repository.save_simulation(game_id, record.revision, result)
        return simulation_response(saved)
