from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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

    service_player_id: str
    engine_player_id: str
    deck_id: str


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_id: str
    viewer_player_id: str
    participants: tuple[CreateMatchParticipantRequest, CreateMatchParticipantRequest]
    rng_seed: int | None = None


class SubmitMulliganRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str
    card_instance_ids: tuple[str, ...] = Field(default_factory=tuple)


class PlayCardRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str
    card_instance_id: str
    target_row: str | None = None
    target_card_instance_id: str | None = None
    secondary_target_card_instance_id: str | None = None


class PassTurnRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str


class LeaveMatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str


class UseLeaderAbilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str
    target_row: str | None = None
    target_player: str | None = None
    target_card_instance_id: str | None = None
    secondary_target_card_instance_id: str | None = None
    selected_card_instance_ids: tuple[str, ...] = Field(default_factory=tuple)


class ResolveChoiceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_player_id: str
    choice_id: str
    selected_card_instance_ids: tuple[str, ...] = Field(default_factory=tuple)
    selected_rows: tuple[str, ...] = Field(default_factory=tuple)
