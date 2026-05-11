from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from gwent_engine.core.errors import IllegalActionError

from gwent_service.application.errors import (
    MatchAlreadyExistsError,
    MatchNotFoundError,
    MatchPhaseError,
    MatchServiceError,
    MatchVersionConflictError,
    MulliganAlreadySubmittedError,
    MulliganSelectionError,
    UnknownMatchPlayerError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(MatchAlreadyExistsError)
    @app.exception_handler(MatchVersionConflictError)
    async def _handle_conflict_errors(
        request: Request,
        exc: MatchAlreadyExistsError | MatchVersionConflictError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(MatchNotFoundError)
    async def _handle_match_not_found(
        request: Request,
        exc: MatchNotFoundError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(UnknownMatchPlayerError)
    async def _handle_unknown_match_player(
        request: Request,
        exc: UnknownMatchPlayerError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(IllegalActionError)
    @app.exception_handler(MatchPhaseError)
    @app.exception_handler(MulliganAlreadySubmittedError)
    @app.exception_handler(MulliganSelectionError)
    async def _handle_bad_request_errors(
        request: Request,
        exc: MatchServiceError | IllegalActionError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"detail": str(exc)})
