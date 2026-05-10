from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateMatchParticipantCommand:
    service_player_id: str
    engine_player_id: str
    deck_id: str


@dataclass(frozen=True, slots=True)
class CreateMatchCommand:
    match_id: str
    participants: tuple[CreateMatchParticipantCommand, CreateMatchParticipantCommand]
    rng_seed: int | None = None


@dataclass(frozen=True, slots=True)
class SubmitMulliganCommand:
    match_id: str
    service_player_id: str
    card_instance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayCardCommand:
    match_id: str
    service_player_id: str
    card_instance_id: str
    target_row: str | None = None
    target_card_instance_id: str | None = None
    secondary_target_card_instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class PassTurnCommand:
    match_id: str
    service_player_id: str


@dataclass(frozen=True, slots=True)
class LeaveMatchCommand:
    match_id: str
    service_player_id: str


@dataclass(frozen=True, slots=True)
class UseLeaderAbilityCommand:
    match_id: str
    service_player_id: str
    target_row: str | None = None
    target_player: str | None = None
    target_card_instance_id: str | None = None
    secondary_target_card_instance_id: str | None = None
    selected_card_instance_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolveChoiceCommand:
    match_id: str
    service_player_id: str
    choice_id: str
    selected_card_instance_ids: tuple[str, ...] = ()
    selected_rows: tuple[str, ...] = ()
