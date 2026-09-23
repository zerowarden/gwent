from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

type RowName = Literal["close", "ranged", "siege"]
type NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CardView(BaseModel):
    model_config = ConfigDict(frozen=True)

    instance_id: str
    definition_id: str
    name: str
    faction: str
    card_type: str
    owner_id: str
    zone: str
    row: str | None = None
    battlefield_side: str | None = None
    is_hero: bool


class LeaderView(BaseModel):
    model_config = ConfigDict(frozen=True)

    leader_id: str
    name: str
    faction: str
    used: bool
    disabled: bool
    horn_row: str | None = None


class RowCardsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    close: tuple[CardView, ...] = Field(default_factory=tuple)
    ranged: tuple[CardView, ...] = Field(default_factory=tuple)
    siege: tuple[CardView, ...] = Field(default_factory=tuple)


class PublicPlayerView(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str
    engine_player_id: str
    faction: str
    leader: LeaderView
    deck_count: int
    hand_count: int
    discard: tuple[CardView, ...] = Field(default_factory=tuple)
    rows: RowCardsView
    gems_remaining: int
    round_wins: int
    has_passed: bool


class PendingChoiceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    choice_id: str
    chooser_engine_player_id: str
    kind: str
    source_kind: str
    source_card: CardView | None = None
    source_leader_id: str | None = None
    legal_target_cards: tuple[CardView, ...] = Field(default_factory=tuple)
    legal_rows: tuple[str, ...] = Field(default_factory=tuple)
    min_selections: int
    max_selections: int
    source_row: str | None = None


class MulliganSubmissionStatusView(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str
    submitted: bool


class MatchView(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_id: str
    viewer_player_id: str
    viewer_engine_player_id: str
    opponent_player_id: str
    phase: str
    status: str
    round_number: int
    current_player: str | None = None
    starting_player: str | None = None
    round_starter: str | None = None
    match_winner: str | None = None
    viewer: PublicPlayerView
    opponent: PublicPlayerView
    viewer_hand: tuple[CardView, ...] = Field(default_factory=tuple)
    battlefield_weather: RowCardsView
    pending_choice: PendingChoiceView | None = None
    mulligan_submissions: tuple[MulliganSubmissionStatusView, ...] = Field(default_factory=tuple)


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str


class CreateMatchParticipantRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: NonBlankStr
    engine_player_id: NonBlankStr
    deck_id: NonBlankStr


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_id: NonBlankStr
    viewer_player_id: NonBlankStr
    participants: tuple[CreateMatchParticipantRequest, CreateMatchParticipantRequest]
    rng_seed: int | None = None

    @model_validator(mode="after")
    def _require_unique_participant_ids(self) -> CreateMatchRequest:
        service_player_ids = [participant.service_player_id for participant in self.participants]
        engine_player_ids = [participant.engine_player_id for participant in self.participants]
        if len(set(service_player_ids)) != len(service_player_ids):
            raise ValueError("Participant service_player_id values must be unique.")
        if len(set(engine_player_ids)) != len(engine_player_ids):
            raise ValueError("Participant engine_player_id values must be unique.")
        return self


class SubmitMulliganRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: NonBlankStr
    card_instance_ids: tuple[NonBlankStr, ...] = Field(default_factory=tuple)


class PlayCardRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: NonBlankStr
    card_instance_id: NonBlankStr
    target_row: RowName | None = None
    target_card_instance_id: NonBlankStr | None = None
    secondary_target_card_instance_id: NonBlankStr | None = None


class PassTurnRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: NonBlankStr


class LeaveMatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: NonBlankStr


class UseLeaderAbilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: NonBlankStr
    target_row: RowName | None = None
    target_player: NonBlankStr | None = None
    target_card_instance_id: NonBlankStr | None = None
    secondary_target_card_instance_id: NonBlankStr | None = None
    selected_card_instance_ids: tuple[NonBlankStr, ...] = Field(default_factory=tuple)


class ResolveChoiceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: NonBlankStr
    choice_id: NonBlankStr
    selected_card_instance_ids: tuple[NonBlankStr, ...] = Field(default_factory=tuple)
    selected_rows: tuple[RowName, ...] = Field(default_factory=tuple)
