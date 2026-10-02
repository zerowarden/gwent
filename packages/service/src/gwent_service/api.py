"""HTTP transport: dependency providers, match routes, and error mapping."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from gwent_engine.core.errors import IllegalActionError

from gwent_service.config import ServiceConfig, default_service_config
from gwent_service.domain import (
    MatchAlreadyExistsError,
    MatchNotFoundError,
    MatchPhaseError,
    MatchRepository,
    MatchServiceError,
    MatchVersionConflictError,
    MulliganAlreadySubmittedError,
    MulliganSelectionError,
    UnknownDeckError,
    UnknownMatchPlayerError,
)
from gwent_service.dto import (
    CreateMatchCommand,
    CreateMatchParticipantCommand,
    CreateMatchRequest,
    LeaveMatchCommand,
    LeaveMatchRequest,
    MatchView,
    PassTurnCommand,
    PassTurnRequest,
    PlayCardCommand,
    PlayCardRequest,
    ResolveChoiceCommand,
    ResolveChoiceRequest,
    SubmitMulliganCommand,
    SubmitMulliganRequest,
    UseLeaderAbilityCommand,
    UseLeaderAbilityRequest,
)
from gwent_service.engine_adapter import GwentEngineAdapter
from gwent_service.match_service import MatchService
from gwent_service.persistence import InMemoryMatchRepository, SQLiteMatchRepository


@lru_cache(maxsize=1)
def get_service_config() -> ServiceConfig:
    return default_service_config()


@lru_cache(maxsize=1)
def get_engine_adapter() -> GwentEngineAdapter:
    return GwentEngineAdapter(get_service_config())


@lru_cache(maxsize=1)
def get_match_repository() -> MatchRepository:
    config = get_service_config()
    if config.repository_backend == "memory":
        return InMemoryMatchRepository()
    if config.repository_backend == "sqlite":
        return SQLiteMatchRepository(config.sqlite_path)
    raise ValueError(f"Unsupported repository backend: {config.repository_backend!r}")


def get_match_service() -> MatchService:
    return MatchService(
        repository=get_match_repository(),
        adapter=get_engine_adapter(),
    )


router = APIRouter(prefix="/matches", tags=["matches"])
MatchServiceDep = Annotated[MatchService, Depends(get_match_service)]


@router.post("", response_model=MatchView)
def create_match(
    request: CreateMatchRequest,
    match_service: MatchServiceDep,
) -> MatchView:
    first_participant, second_participant = request.participants
    return match_service.create_match(
        CreateMatchCommand(
            match_id=request.match_id,
            participants=(
                CreateMatchParticipantCommand(
                    service_player_id=first_participant.service_player_id,
                    engine_player_id=first_participant.engine_player_id,
                    deck_id=first_participant.deck_id,
                ),
                CreateMatchParticipantCommand(
                    service_player_id=second_participant.service_player_id,
                    engine_player_id=second_participant.engine_player_id,
                    deck_id=second_participant.deck_id,
                ),
            ),
            rng_seed=request.rng_seed,
        ),
        viewer_service_player_id=request.viewer_player_id,
    )


@router.get("/{match_id}", response_model=MatchView)
def get_match(
    match_id: str,
    viewer_player_id: str,
    match_service: MatchServiceDep,
) -> MatchView:
    return match_service.get_match(match_id, viewer_service_player_id=viewer_player_id)


@router.post("/{match_id}/mulligan", response_model=MatchView)
def submit_mulligan(
    match_id: str,
    request: SubmitMulliganRequest,
    match_service: MatchServiceDep,
) -> MatchView:
    return match_service.submit_mulligan(
        SubmitMulliganCommand(
            match_id=match_id,
            service_player_id=request.service_player_id,
            card_instance_ids=request.card_instance_ids,
        )
    )


@router.post("/{match_id}/actions/play-card", response_model=MatchView)
def play_card(
    match_id: str,
    request: PlayCardRequest,
    match_service: MatchServiceDep,
) -> MatchView:
    return match_service.play_card(
        PlayCardCommand(
            match_id=match_id,
            service_player_id=request.service_player_id,
            card_instance_id=request.card_instance_id,
            target_row=request.target_row,
            target_card_instance_id=request.target_card_instance_id,
        )
    )


@router.post("/{match_id}/actions/pass", response_model=MatchView)
def pass_turn(
    match_id: str,
    request: PassTurnRequest,
    match_service: MatchServiceDep,
) -> MatchView:
    return match_service.pass_turn(
        PassTurnCommand(
            match_id=match_id,
            service_player_id=request.service_player_id,
        )
    )


@router.post("/{match_id}/actions/leave", response_model=MatchView)
def leave_match(
    match_id: str,
    request: LeaveMatchRequest,
    match_service: MatchServiceDep,
) -> MatchView:
    return match_service.leave_match(
        LeaveMatchCommand(
            match_id=match_id,
            service_player_id=request.service_player_id,
        )
    )


@router.post("/{match_id}/actions/use-leader", response_model=MatchView)
def use_leader(
    match_id: str,
    request: UseLeaderAbilityRequest,
    match_service: MatchServiceDep,
) -> MatchView:
    return match_service.use_leader(
        UseLeaderAbilityCommand(
            match_id=match_id,
            service_player_id=request.service_player_id,
            target_card_instance_id=request.target_card_instance_id,
            selected_card_instance_ids=request.selected_card_instance_ids,
        )
    )


@router.post("/{match_id}/actions/resolve-choice", response_model=MatchView)
def resolve_choice(
    match_id: str,
    request: ResolveChoiceRequest,
    match_service: MatchServiceDep,
) -> MatchView:
    return match_service.resolve_choice(
        ResolveChoiceCommand(
            match_id=match_id,
            service_player_id=request.service_player_id,
            choice_id=request.choice_id,
            selected_card_instance_ids=request.selected_card_instance_ids,
        )
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
    @app.exception_handler(UnknownDeckError)
    async def _handle_bad_request_errors(
        request: Request,
        exc: MatchServiceError | IllegalActionError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"detail": str(exc)})
