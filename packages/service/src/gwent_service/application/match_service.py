from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from gwent_engine.core import Phase
from gwent_engine.core.actions import GameAction
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState

from gwent_service.application.commands import (
    CreateMatchCommand,
    LeaveMatchCommand,
    PassTurnCommand,
    PlayCardCommand,
    ResolveChoiceCommand,
    SubmitMulliganCommand,
    UseLeaderAbilityCommand,
)
from gwent_service.application.dto import MatchView
from gwent_service.application.errors import (
    MatchNotFoundError,
    MatchPhaseError,
    UnknownMatchPlayerError,
)
from gwent_service.application.projections import project_match_for_player
from gwent_service.application.snapshot import (
    MatchSnapshot,
    snapshot_from_stored_match,
    stored_match_from_snapshot,
)
from gwent_service.application.staging import (
    mulligan_submission_map,
    mulligans_are_complete,
    stage_mulligan_submission,
)
from gwent_service.domain.models import StagedMulliganSubmission, StoredPlayerSlot
from gwent_service.domain.repositories import MatchRepository
from gwent_service.engine.contracts import (
    CreateMatchStateSpec,
    EngineAdapter,
    EnginePlayerDeckSpec,
    EngineTransitionResult,
)

MatchRngFactory = Callable[[int | None, int], SupportsRandom | None]
Clock = Callable[[], datetime]
BuildAction = Callable[[MatchSnapshot, StoredPlayerSlot], GameAction]


class MatchService:
    def __init__(
        self,
        repository: MatchRepository,
        adapter: EngineAdapter,
        *,
        rng_factory: MatchRngFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository: MatchRepository = repository
        self._adapter: EngineAdapter = adapter
        self._rng_factory: MatchRngFactory = rng_factory or _default_rng_factory
        self._clock: Clock = clock or _utc_now

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
        now = self._clock()
        snapshot = MatchSnapshot(
            match_id=command.match_id,
            state=start_transition.next_state,
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
        )
        _ = self._require_player_slot(snapshot, viewer_service_player_id)
        self._repository.create(stored_match_from_snapshot(snapshot, adapter=self._adapter))
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
            snapshot.staged_mulligans,
            StagedMulliganSubmission(
                engine_player_id=viewer_slot.engine_player_id,
                card_instance_ids=command.card_instance_ids,
            ),
            valid_engine_player_ids=frozenset(
                slot.engine_player_id for slot in snapshot.player_slots
            ),
        )
        if not mulligans_are_complete(next_staged_mulligans):
            updated_snapshot = self._record_staged_mulligans(snapshot, next_staged_mulligans)
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
                secondary_target_card_instance_id=command.secondary_target_card_instance_id,
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
        def build_action(snapshot: MatchSnapshot, viewer_slot: StoredPlayerSlot) -> GameAction:
            target_player = None
            if command.target_player is not None:
                target_player = self._require_player_slot(
                    snapshot,
                    command.target_player,
                ).engine_player_id
            return self._adapter.build_use_leader_ability_action(
                player_id=viewer_slot.engine_player_id,
                target_row=command.target_row,
                target_player=target_player,
                target_card_instance_id=command.target_card_instance_id,
                secondary_target_card_instance_id=command.secondary_target_card_instance_id,
                selected_card_instance_ids=command.selected_card_instance_ids,
            )

        return self._execute_action(command.match_id, command.service_player_id, build_action)

    def resolve_choice(self, command: ResolveChoiceCommand) -> MatchView:
        def build_action(_snapshot: MatchSnapshot, viewer_slot: StoredPlayerSlot) -> GameAction:
            return self._adapter.build_resolve_choice_action(
                player_id=viewer_slot.engine_player_id,
                choice_id=command.choice_id,
                selected_card_instance_ids=command.selected_card_instance_ids,
                selected_rows=command.selected_rows,
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
        try:
            return snapshot.slot_for_service_player(service_player_id)
        except KeyError as exc:
            raise UnknownMatchPlayerError(service_player_id, snapshot.match_id) from exc

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
        updated_snapshot = replace(
            snapshot,
            state=transition.next_state,
            event_log_payloads=(
                snapshot.event_log_payloads + self._adapter.serialize_events(transition.events)
            ),
            staged_mulligans=(
                snapshot.staged_mulligans if staged_mulligans is None else staged_mulligans
            ),
            version=snapshot.version + 1,
            updated_at=self._clock(),
        )
        self._save(snapshot, updated_snapshot)
        return updated_snapshot

    def _record_staged_mulligans(
        self,
        snapshot: MatchSnapshot,
        staged_mulligans: tuple[StagedMulliganSubmission, ...],
    ) -> MatchSnapshot:
        return replace(
            snapshot,
            staged_mulligans=staged_mulligans,
            version=snapshot.version + 1,
            updated_at=self._clock(),
        )

    def _save(self, previous_snapshot: MatchSnapshot, updated_snapshot: MatchSnapshot) -> None:
        self._repository.update(
            stored_match_from_snapshot(updated_snapshot, adapter=self._adapter),
            expected_version=previous_snapshot.version,
        )

    def _rng_for_state(self, state: GameState) -> SupportsRandom | None:
        return self._rng_factory(state.rng_seed, state.event_counter)


def _default_rng_factory(seed: int | None, event_counter: int) -> SupportsRandom | None:
    if seed is None:
        return None
    from gwent_service.engine.randomness import StdlibRandomAdapter

    return StdlibRandomAdapter(seed + event_counter)


def _utc_now() -> datetime:
    return datetime.now(UTC)
