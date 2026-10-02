from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from gwent_engine.core import Phase
from gwent_engine.core.actions import GameAction
from gwent_engine.core.randomness import SeededRandom, SupportsRandom
from gwent_engine.core.state import GameState

from gwent_service.domain import (
    MatchNotFoundError,
    MatchPhaseError,
    MatchRepository,
    MatchSnapshot,
    MulliganAlreadySubmittedError,
    StagedMulliganSubmission,
    StoredMatch,
    StoredPlayerSlot,
)
from gwent_service.dto import (
    CreateMatchCommand,
    LeaveMatchCommand,
    MatchView,
    PassTurnCommand,
    PlayCardCommand,
    ResolveChoiceCommand,
    SubmitMulliganCommand,
    UseLeaderAbilityCommand,
)
from gwent_service.engine_adapter import (
    CreateMatchStateSpec,
    EnginePlayerDeckSpec,
    EngineTransitionResult,
    GwentEngineAdapter,
)
from gwent_service.projections import project_match_for_player

MatchRngFactory = Callable[[int | None, int], SupportsRandom]
BuildAction = Callable[[MatchSnapshot, StoredPlayerSlot], GameAction]


class MatchService:
    def __init__(
        self,
        repository: MatchRepository,
        adapter: GwentEngineAdapter,
        *,
        rng_factory: MatchRngFactory | None = None,
    ) -> None:
        self._repository: MatchRepository = repository
        self._adapter: GwentEngineAdapter = adapter
        self._rng_factory: MatchRngFactory = rng_factory or _default_rng_factory

    def create_match(
        self,
        command: CreateMatchCommand,
        *,
        viewer_service_player_id: str,
    ) -> MatchView:
        first_participant, second_participant = command.participants
        initial_state = self._adapter.create_match_state(
            CreateMatchStateSpec(
                game_id=command.match_id,
                players=(
                    EnginePlayerDeckSpec(
                        player_id=first_participant.engine_player_id,
                        deck_id=first_participant.deck_id,
                    ),
                    EnginePlayerDeckSpec(
                        player_id=second_participant.engine_player_id,
                        deck_id=second_participant.deck_id,
                    ),
                ),
                rng_seed=command.rng_seed,
            )
        )
        start_transition = self._adapter.apply_engine_action(
            initial_state,
            self._adapter.build_start_game_action(
                starting_player_id=first_participant.engine_player_id,
            ),
            rng=self._rng_for_state(initial_state),
        )
        now = _utc_now()
        snapshot = MatchSnapshot(
            stored=StoredMatch(
                match_id=command.match_id,
                state_payload=self._adapter.serialize_state(start_transition.next_state),
                event_log_payloads=self._adapter.serialize_events(start_transition.events),
                player_slots=(
                    StoredPlayerSlot(
                        service_player_id=first_participant.service_player_id,
                        engine_player_id=first_participant.engine_player_id,
                        deck_id=first_participant.deck_id,
                    ),
                    StoredPlayerSlot(
                        service_player_id=second_participant.service_player_id,
                        engine_player_id=second_participant.engine_player_id,
                        deck_id=second_participant.deck_id,
                    ),
                ),
                staged_mulligans=(),
                version=1,
                created_at=now,
                updated_at=now,
            ),
            state=start_transition.next_state,
        )
        _ = self._require_player_slot(snapshot, viewer_service_player_id)
        self._repository.create(snapshot.stored)
        return project_match_for_player(
            snapshot,
            viewer_service_player_id,
            adapter=self._adapter,
        )

    def get_match(self, match_id: str, *, viewer_service_player_id: str) -> MatchView:
        snapshot = self._load_match(match_id)
        return project_match_for_player(
            snapshot,
            viewer_service_player_id,
            adapter=self._adapter,
        )

    def submit_mulligan(self, command: SubmitMulliganCommand) -> MatchView:
        snapshot = self._load_match(command.match_id)
        viewer_slot = self._require_player_slot(snapshot, command.service_player_id)
        if snapshot.state.phase != Phase.MULLIGAN:
            raise MatchPhaseError("Mulligan submissions are only valid during the mulligan phase.")

        self._adapter.validate_mulligan_selection(
            snapshot.state,
            player_id=viewer_slot.engine_player_id,
            card_instance_ids=command.card_instance_ids,
        )

        next_staged_mulligans = stage_mulligan_submission(
            snapshot.stored.staged_mulligans,
            StagedMulliganSubmission(
                engine_player_id=viewer_slot.engine_player_id,
                card_instance_ids=command.card_instance_ids,
            ),
        )
        if len(next_staged_mulligans) < len(snapshot.stored.player_slots):
            updated_snapshot = MatchSnapshot(
                stored=_next_version(
                    replace(snapshot.stored, staged_mulligans=next_staged_mulligans)
                ),
                state=snapshot.state,
            )
            self._save(snapshot, updated_snapshot)
            return project_match_for_player(
                updated_snapshot,
                command.service_player_id,
                adapter=self._adapter,
            )

        transition = self._apply_transition(
            snapshot,
            self._adapter.build_resolve_mulligans_action(
                player_order=tuple(str(player.player_id) for player in snapshot.state.players),
                selections_by_player_id=mulligan_submission_map(next_staged_mulligans),
            ),
        )
        updated_snapshot = self._persist_transition(
            snapshot,
            transition,
            staged_mulligans=(),
        )
        return project_match_for_player(
            updated_snapshot,
            command.service_player_id,
            adapter=self._adapter,
        )

    def play_card(self, command: PlayCardCommand) -> MatchView:
        def build_action(_snapshot: MatchSnapshot, viewer_slot: StoredPlayerSlot) -> GameAction:
            return self._adapter.build_play_card_action(
                player_id=viewer_slot.engine_player_id,
                card_instance_id=command.card_instance_id,
                target_row=command.target_row,
                target_card_instance_id=command.target_card_instance_id,
            )

        return self._execute_action(command.match_id, command.service_player_id, build_action)

    def pass_turn(self, command: PassTurnCommand) -> MatchView:
        def build_action(_snapshot: MatchSnapshot, viewer_slot: StoredPlayerSlot) -> GameAction:
            return self._adapter.build_player_action(
                kind="pass",
                player_id=viewer_slot.engine_player_id,
            )

        return self._execute_action(command.match_id, command.service_player_id, build_action)

    def leave_match(self, command: LeaveMatchCommand) -> MatchView:
        def build_action(_snapshot: MatchSnapshot, viewer_slot: StoredPlayerSlot) -> GameAction:
            return self._adapter.build_player_action(
                kind="leave",
                player_id=viewer_slot.engine_player_id,
            )

        return self._execute_action(command.match_id, command.service_player_id, build_action)

    def use_leader(self, command: UseLeaderAbilityCommand) -> MatchView:
        def build_action(_snapshot: MatchSnapshot, viewer_slot: StoredPlayerSlot) -> GameAction:
            return self._adapter.build_use_leader_ability_action(
                player_id=viewer_slot.engine_player_id,
                target_card_instance_id=command.target_card_instance_id,
                selected_card_instance_ids=command.selected_card_instance_ids,
            )

        return self._execute_action(command.match_id, command.service_player_id, build_action)

    def resolve_choice(self, command: ResolveChoiceCommand) -> MatchView:
        def build_action(_snapshot: MatchSnapshot, viewer_slot: StoredPlayerSlot) -> GameAction:
            return self._adapter.build_resolve_choice_action(
                player_id=viewer_slot.engine_player_id,
                choice_id=command.choice_id,
                selected_card_instance_ids=command.selected_card_instance_ids,
            )

        return self._execute_action(command.match_id, command.service_player_id, build_action)

    def _execute_action(
        self,
        match_id: str,
        service_player_id: str,
        build_action: BuildAction,
    ) -> MatchView:
        snapshot = self._load_match(match_id)
        viewer_slot = self._require_player_slot(snapshot, service_player_id)
        transition = self._apply_transition(snapshot, build_action(snapshot, viewer_slot))
        updated_snapshot = self._persist_transition(snapshot, transition)
        return project_match_for_player(
            updated_snapshot,
            service_player_id,
            adapter=self._adapter,
        )

    def _load_match(self, match_id: str) -> MatchSnapshot:
        stored_match = self._repository.get(match_id)
        if stored_match is None:
            raise MatchNotFoundError(match_id)
        return snapshot_from_stored_match(stored_match, adapter=self._adapter)

    @staticmethod
    def _require_player_slot(snapshot: MatchSnapshot, service_player_id: str) -> StoredPlayerSlot:
        return snapshot.stored.slot_for_service_player(service_player_id)

    def _apply_transition(
        self,
        snapshot: MatchSnapshot,
        action: GameAction,
    ) -> EngineTransitionResult:
        return self._adapter.apply_engine_action(
            snapshot.state,
            action,
            rng=self._rng_for_state(snapshot.state),
        )

    def _persist_transition(
        self,
        snapshot: MatchSnapshot,
        transition: EngineTransitionResult,
        *,
        staged_mulligans: tuple[StagedMulliganSubmission, ...] | None = None,
    ) -> MatchSnapshot:
        updated_snapshot = MatchSnapshot(
            stored=_next_version(
                replace(
                    snapshot.stored,
                    event_log_payloads=(
                        snapshot.stored.event_log_payloads
                        + self._adapter.serialize_events(transition.events)
                    ),
                    staged_mulligans=(
                        snapshot.stored.staged_mulligans
                        if staged_mulligans is None
                        else staged_mulligans
                    ),
                )
            ),
            state=transition.next_state,
        )
        self._save(snapshot, updated_snapshot)
        return updated_snapshot

    def _save(self, previous_snapshot: MatchSnapshot, updated_snapshot: MatchSnapshot) -> None:
        self._repository.update(
            stored_match_from_snapshot(updated_snapshot, adapter=self._adapter),
            expected_version=previous_snapshot.stored.version,
        )

    def _rng_for_state(self, state: GameState) -> SupportsRandom:
        return self._rng_factory(state.rng_seed, state.event_counter)


def _default_rng_factory(seed: int | None, event_counter: int) -> SupportsRandom:
    return SeededRandom(None if seed is None else seed + event_counter)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _next_version(stored: StoredMatch) -> StoredMatch:
    return replace(stored, version=stored.version + 1, updated_at=_utc_now())


def stage_mulligan_submission(
    staged_mulligans: tuple[StagedMulliganSubmission, ...],
    submission: StagedMulliganSubmission,
) -> tuple[StagedMulliganSubmission, ...]:
    if any(staged.engine_player_id == submission.engine_player_id for staged in staged_mulligans):
        raise MulliganAlreadySubmittedError(submission.engine_player_id)
    return (*staged_mulligans, submission)


def mulligan_submission_map(
    staged_mulligans: tuple[StagedMulliganSubmission, ...],
) -> dict[str, tuple[str, ...]]:
    return {
        submission.engine_player_id: submission.card_instance_ids for submission in staged_mulligans
    }


def snapshot_from_stored_match(
    stored_match: StoredMatch,
    *,
    adapter: GwentEngineAdapter,
) -> MatchSnapshot:
    return MatchSnapshot(
        stored=stored_match,
        state=adapter.deserialize_state(stored_match.state_payload),
    )


def stored_match_from_snapshot(
    snapshot: MatchSnapshot,
    *,
    adapter: GwentEngineAdapter,
) -> StoredMatch:
    return replace(snapshot.stored, state_payload=adapter.serialize_state(snapshot.state))
