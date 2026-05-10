from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from gwent_service.application.commands import (
    CreateMatchCommand,
    CreateMatchParticipantCommand,
    LeaveMatchCommand,
    PassTurnCommand,
    PlayCardCommand,
    ResolveChoiceCommand,
    SubmitMulliganCommand,
    UseLeaderAbilityCommand,
)
from gwent_service.application.dto import (
    CreateMatchRequest,
    LeaveMatchRequest,
    MatchView,
    PassTurnRequest,
    PlayCardRequest,
    ResolveChoiceRequest,
    SubmitMulliganRequest,
    UseLeaderAbilityRequest,
)
from gwent_service.application.match_service import MatchService
from gwent_service.dependencies import get_match_service

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
            secondary_target_card_instance_id=request.secondary_target_card_instance_id,
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
            target_row=request.target_row,
            target_player=request.target_player,
            target_card_instance_id=request.target_card_instance_id,
            secondary_target_card_instance_id=request.secondary_target_card_instance_id,
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
            selected_rows=request.selected_rows,
        )
    )
