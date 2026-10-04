"""Local async FastAPI -> stdin/stdout mathematical engine bridge.

Run: python engine_server.py --config engine_config.json
Python 3.11+. Engine protocol: JSON stdin -> {"move_index": int} stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Response, Request

log = logging.getLogger('engine_bridge')
TIMEOUT_SECONDS = 2.0


class EngineError(RuntimeError):
    pass


def candidate_indices(state: dict[str, Any]) -> list[int]:
    """Candidates are explicitly declared, not inferred from game rules."""
    key = 'legal_moves' if 'legal_moves' in state else 'cards'
    items = state.get(key)
    if not isinstance(items, list) or not 1 <= len(items) <= 10_000:
        raise ValueError('Provide a nonempty legal_moves or cards array (max 10000)')
    # DOM cards are candidates only; caller must restrict them to actionable ones.
    return list(range(len(items)))


class EngineRunner:
    def __init__(self, command: list[str], *, cwd: Path, max_parallel=4):
        if not command or any(not isinstance(arg, str) or not arg for arg in command):
            raise ValueError('command must be a nonempty argv array')
        if type(max_parallel) is not int or max_parallel < 1:
            raise ValueError('max_parallel must be a positive integer')
        self.command = command
        self.cwd = cwd
        self.slots = asyncio.Semaphore(max_parallel)
        self.tasks = set()

    def _done(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()  # retrieve errors even after a client timed out

    async def _invoke(self, payload: bytes, indices: list[int]) -> int:
        async with self.slots:
            process = None
            try:
                options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
                process = await asyncio.create_subprocess_exec(
                    *self.command, cwd=self.cwd, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    **options)
                stdout, stderr = await process.communicate(payload)
                if process.returncode != 0:
                    raise EngineError('Engine exited with an error')
                if len(stdout) > 65_536:
                    raise EngineError('Engine response exceeds 64 KiB')
                try:
                    result = json.loads(stdout.decode('utf-8'))
                except (ValueError, UnicodeError) as exc:
                    raise EngineError('Engine returned invalid JSON') from exc
                index = result.get('move_index') if isinstance(result, dict) else None
                if type(index) is not int or index not in indices:
                    raise EngineError('Engine returned an invalid move index')
                return result
            except OSError as exc:
                raise EngineError('Cannot launch engine') from exc
            finally:
                if process is not None and process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    # Cleanup runs in this task; a timeout response doesn't wait
                    # for it. Keep the concurrency slot until cleanup completes.
                    try:
                        await asyncio.wait_for(process.communicate(), timeout=.5)
                    except (TimeoutError, OSError):
                        log.warning('engine_cleanup_incomplete=true')

    async def analyze_details(self, state: dict[str, Any]):
        indices = candidate_indices(state)
        try:
            payload = json.dumps(state, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError) as exc:
            raise ValueError('State must contain finite JSON values') from exc
        if len(payload) > 1_048_576:
            raise ValueError('State exceeds 1 MiB')
        # The deadline includes semaphore queueing and engine startup.
        task = asyncio.create_task(self._invoke(payload, indices))
        self.tasks.add(task)
        task.add_done_callback(self._done)
        try:
            done, _ = await asyncio.wait({task}, timeout=TIMEOUT_SECONDS)
            if done:
                return task.result(), False
            task.cancel()
            index = random.choice(indices)
            log.warning('engine_timeout=true fallback=random candidate_count=%d', len(indices))
            return {'move_index':index,'source':'timeout fallback'}, True
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def analyze(self, state):
        result, fallback = await self.analyze_details(state)
        return result['move_index'], fallback

    async def close(self):
        pending = list(self.tasks)
        for task in pending:
            if task.cancelling() == 0:
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def create_app(config_path: str | Path = 'engine_config.json', *,
               config_data=None, runner_factory=None) -> FastAPI:
    path = Path(config_path).resolve()
    config = (config_data if config_data is not None else
              json.loads(path.read_text(encoding='utf-8')))
    command = config.get('command')
    cwd = (path.parent / config.get('cwd', '.')).resolve()
    gated=config.get('require_room_ready',False)
    ready_sessions=set()
    allowed_sessions=set(config.get('session_ids',[]))

    def authorize(request):
        sid=request.headers.get('X-QA-Session','')
        if request.headers.get('X-QA-Token')!=config.get('gate_token') or sid not in allowed_sessions:
            raise HTTPException(status_code=401,detail='Unknown browser session')
        return sid

    def make_runner():
        return (runner_factory() if runner_factory is not None else
                EngineRunner(command,cwd=cwd,max_parallel=config.get('max_parallel',4)))

    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = None if gated else make_runner()
        try:
            yield
        finally:
            if app.state.engine is not None:await app.state.engine.close()

    app = FastAPI(title='Local mathematical engine bridge', lifespan=lifespan)

    @app.post('/room-ready')
    async def room_ready(request:Request,state:dict[str,Any]=Body(...)):
        if not gated:raise HTTPException(status_code=404)
        sid=authorize(request)
        try:candidate_indices(state)
        except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc
        ready_sessions.add(sid)
        return {'ready':True}

    @app.post('/room-left')
    async def room_left(request:Request):
        if not gated:raise HTTPException(status_code=404)
        ready_sessions.discard(authorize(request))
        return {'ready':False}

    @app.post('/analyze')
    async def analyze(request:Request,response: Response, state: dict[str, Any] = Body(...)):
        if gated:
            if authorize(request) not in ready_sessions:raise HTTPException(status_code=409,detail='Browser has not entered a ready game room')
            if app.state.engine is None:app.state.engine=make_runner()
        try:
            if hasattr(app.state.engine,'analyze_details'):
                result, fallback = await app.state.engine.analyze_details(state)
            else:
                index, fallback = await app.state.engine.analyze(state)
                result = {'move_index':index}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EngineError as exc:
            log.error('engine_error=true')
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        response.headers['X-Engine-Fallback'] = 'timeout' if fallback else 'none'
        return {**result, 'fallback':fallback}

    @app.get('/health')
    async def health():
        return {'status': 'ok'}  # liveness, not a probe of engine readiness

    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='engine_config.json')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(args.config), host='127.0.0.1', port=5000)
