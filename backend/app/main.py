from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.api.games import router
from backend.app.core.errors import (AnalysisNotFound, CalculationLimitExceeded, GameNotFound,
    InvalidEngineInput, RevisionConflict)
from backend.app.services.games import GameService
from backend.app.services.repository import GameRepository, InMemoryGameRepository


def create_app(repository: GameRepository | None = None) -> FastAPI:
    application = FastAPI(title='Scopa Engine API', version='0.1.0', description='HTTP adapter for the independent Scopa engine.')
    application.state.game_service = GameService(repository if repository is not None else InMemoryGameRepository())
    application.include_router(router)
    errors = {GameNotFound: (404, 'game_not_found'), AnalysisNotFound: (404, 'analysis_not_found'),
        RevisionConflict: (409, 'revision_conflict'), InvalidEngineInput: (422, 'invalid_engine_input'),
        CalculationLimitExceeded: (429, 'calculation_limit_exceeded')}
    async def domain_error(request: Request, error: Exception):
        status, code = errors[type(error)]
        return JSONResponse(status_code=status, content={'detail': {'code': code, 'message': str(error)}})
    for exception in errors:
        application.add_exception_handler(exception, domain_error)
    return application


app = create_app()
