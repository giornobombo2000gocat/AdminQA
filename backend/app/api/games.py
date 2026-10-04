from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response

from backend.app.schemas.games import AnalyzeRequest, CreateGameRequest, GameResponse, SimulateRequest, UpdateStateRequest
from backend.app.schemas.results import AnalysisResponse, SimulationResponse
from backend.app.services.games import GameService

router = APIRouter(prefix='/api/games', tags=['games'])


def get_service(request: Request) -> GameService:
    return request.app.state.game_service


Service = Annotated[GameService, Depends(get_service)]


@router.post('', response_model=GameResponse, status_code=201)
def create_game(body: CreateGameRequest, response: Response, service: Service):
    result = service.create(body)
    response.headers['Location'] = f'/api/games/{result.id}'
    return result


@router.get('/{id}', response_model=GameResponse)
def get_game(id: UUID, service: Service):
    return service.get(id)


@router.post('/{id}/state', response_model=GameResponse)
def update_state(id: UUID, body: UpdateStateRequest, service: Service):
    return service.update_state(id, body)


@router.post('/{id}/analyze', response_model=AnalysisResponse)
def analyze_game(id: UUID, body: AnalyzeRequest, service: Service):
    return service.analyze(id, body)


@router.get('/{id}/analysis', response_model=AnalysisResponse)
def get_analysis(id: UUID, service: Service):
    return service.get_analysis(id)


@router.post('/{id}/simulate', response_model=SimulationResponse)
def simulate_game(id: UUID, body: SimulateRequest, service: Service):
    return service.simulate(id, body)
