from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from gwent_engine.core.actions import GameAction
from gwent_engine.core.randomness import SupportsRandom
from gwent_shared.error_translation import translate_exception

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
from gwent_service.application.staging import (
    mulligan_submission_map,
    mulligans_are_complete,
    stage_mulligan_submission,
)
from gwent_service.application.state_payload import (
    state_event_counter,
    state_phase,
    state_player_order,
    state_rng_seed,
)
from gwent_service.domain.models import StagedMulliganSubmission, StoredMatch, StoredPlayerSlot
from gwent_service.domain.repositories import MatchRepository
from gwent_service.engine.contracts import (
    CreateMatchStateSpec,
    EngineAdapter,
    EnginePlayerDeckSpec,
    EngineTransitionResult,
)

MatchRngFactory = Callable[[int | None, int], SupportsRandom | None]
Clock = Callable[[], datetime]


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
        initial_payload = self._adapter.serialize_state(initial_state)
        start_transition = self._adapter.apply_engine_action(
            initial_state,
            self._adapter.build_start_game_action(
                starting_player_id=command.participants[0].engine_player_id,
            ),
            rng=self._rng_for_state_payload(initial_payload),
        )
        now = self._clock()
        stored_match = StoredMatch(
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
            version=1,
            created_at=now,
            updated_at=now,
        )
        self._repository.create(stored_match)
        return project_match_for_player(
            stored_match,
            viewer_service_player_id,
            adapter=self._adapter,
        )

    def get_match(self, match_id: str, *, viewer_service_player_id: str) -> MatchView:
        stored_match = self._load_match(match_id)
        return project_match_for_player(
            stored_match,
            viewer_service_player_id,
            adapter=self._adapter,
        )

    def submit_mulligan(self, command: SubmitMulliganCommand) -> MatchView:
        stored_match = self._load_match(command.match_id)
        viewer_slot = self._require_player_slot(stored_match, command.service_player_id)
        if state_phase(stored_match.state_payload) != "mulligan":
            raise MatchPhaseError("Mulligan submissions are only valid during the mulligan phase.")

        next_staged_mulligans = stage_mulligan_submission(
            stored_match.staged_mulligans,
            StagedMulliganSubmission(
                engine_player_id=viewer_slot.engine_player_id,
                card_instance_ids=command.card_instance_ids,
            ),
            valid_engine_player_ids=frozenset(
                slot.engine_player_id for slot in stored_match.player_slots
            ),
        )
        if not mulligans_are_complete(next_staged_mulligans):
            updated_match = self._replace_match(
                stored_match,
                staged_mulligans=next_staged_mulligans,
                version=stored_match.version + 1,
            )
            self._repository.update(updated_match)
            return project_match_for_player(
                updated_match,
                command.service_player_id,
                adapter=self._adapter,
            )

        transition = self._apply_transition(
            stored_match,
            self._adapter.build_resolve_mulligans_action(
                player_order=state_player_order(stored_match.state_payload),
                selections_by_player_id=mulligan_submission_map(next_staged_mulligans),
            ),
        )
        updated_match = self._persist_transition(
            stored_match,
            transition,
            staged_mulligans=(),
        )
        return project_match_for_player(
            updated_match,
            command.service_player_id,
            adapter=self._adapter,
        )

    def play_card(self, command: PlayCardCommand) -> MatchView:
        stored_match = self._load_match(command.match_id)
        viewer_slot = self._require_player_slot(stored_match, command.service_player_id)
        transition = self._apply_transition(
            stored_match,
            self._adapter.build_play_card_action(
                player_id=viewer_slot.engine_player_id,
                card_instance_id=command.card_instance_id,
                target_row=command.target_row,
                target_card_instance_id=command.target_card_instance_id,
                secondary_target_card_instance_id=command.secondary_target_card_instance_id,
            ),
        )
        updated_match = self._persist_transition(stored_match, transition)
        return project_match_for_player(
            updated_match,
            command.service_player_id,
            adapter=self._adapter,
        )

    def pass_turn(self, command: PassTurnCommand) -> MatchView:
        stored_match = self._load_match(command.match_id)
        viewer_slot = self._require_player_slot(stored_match, command.service_player_id)
        transition = self._apply_transition(
            stored_match,
            self._adapter.build_player_action(
                kind="pass",
                player_id=viewer_slot.engine_player_id,
            ),
        )
        updated_match = self._persist_transition(stored_match, transition)
        return project_match_for_player(
            updated_match,
            command.service_player_id,
            adapter=self._adapter,
        )

    def leave_match(self, command: LeaveMatchCommand) -> MatchView:
        stored_match = self._load_match(command.match_id)
        viewer_slot = self._require_player_slot(stored_match, command.service_player_id)
        transition = self._apply_transition(
            stored_match,
            self._adapter.build_player_action(
                kind="leave",
                player_id=viewer_slot.engine_player_id,
            ),
        )
        updated_match = self._persist_transition(stored_match, transition)
        return project_match_for_player(
            updated_match,
            command.service_player_id,
            adapter=self._adapter,
        )

    def use_leader(self, command: UseLeaderAbilityCommand) -> MatchView:
        stored_match = self._load_match(command.match_id)
        viewer_slot = self._require_player_slot(stored_match, command.service_player_id)
        target_player = None
        if command.target_player is not None:
            target_player = self._require_player_slot(
                stored_match,
                command.target_player,
            ).engine_player_id
        transition = self._apply_transition(
            stored_match,
            self._adapter.build_use_leader_ability_action(
                player_id=viewer_slot.engine_player_id,
                target_row=command.target_row,
                target_player=target_player,
                target_card_instance_id=command.target_card_instance_id,
                secondary_target_card_instance_id=command.secondary_target_card_instance_id,
                selected_card_instance_ids=command.selected_card_instance_ids,
            ),
        )
        updated_match = self._persist_transition(stored_match, transition)
        return project_match_for_player(
            updated_match,
            command.service_player_id,
            adapter=self._adapter,
        )

    def resolve_choice(self, command: ResolveChoiceCommand) -> MatchView:
        stored_match = self._load_match(command.match_id)
        viewer_slot = self._require_player_slot(stored_match, command.service_player_id)
        transition = self._apply_transition(
            stored_match,
            self._adapter.build_resolve_choice_action(
                player_id=viewer_slot.engine_player_id,
                choice_id=command.choice_id,
                selected_card_instance_ids=command.selected_card_instance_ids,
                selected_rows=command.selected_rows,
            ),
        )
        updated_match = self._persist_transition(stored_match, transition)
        return project_match_for_player(
            updated_match,
            command.service_player_id,
            adapter=self._adapter,
        )

    def _load_match(self, match_id: str) -> StoredMatch:
        stored_match = self._repository.get(match_id)
        if stored_match is None:
            raise MatchNotFoundError(match_id)
        return stored_match

    @staticmethod
    def _require_player_slot(stored_match: StoredMatch, service_player_id: str) -> StoredPlayerSlot:
        return translate_exception(
            lambda: stored_match.slot_for_service_player(service_player_id),
            KeyError,
            lambda _exc: UnknownMatchPlayerError(service_player_id, stored_match.match_id),
        )

    def _apply_transition(
        self,
        stored_match: StoredMatch,
        action: GameAction,
    ) -> EngineTransitionResult:
        state = self._adapter.deserialize_state(stored_match.state_payload)
        return self._adapter.apply_engine_action(
            state,
            action,
            rng=self._rng_for_state_payload(stored_match.state_payload),
        )

    def _persist_transition(
        self,
        stored_match: StoredMatch,
        transition: EngineTransitionResult,
        *,
        staged_mulligans: tuple[StagedMulliganSubmission, ...] | None = None,
    ) -> StoredMatch:
        updated_match = self._replace_match(
            stored_match,
            state_payload=self._adapter.serialize_state(transition.next_state),
            event_log_payloads=(
                stored_match.event_log_payloads + self._adapter.serialize_events(transition.events)
            ),
            staged_mulligans=(
                stored_match.staged_mulligans if staged_mulligans is None else staged_mulligans
            ),
            version=stored_match.version + 1,
        )
        self._repository.update(updated_match)
        return updated_match

    def _replace_match(
        self,
        stored_match: StoredMatch,
        *,
        state_payload: dict[str, object] | None = None,
        event_log_payloads: tuple[dict[str, object], ...] | None = None,
        staged_mulligans: tuple[StagedMulliganSubmission, ...] | None = None,
        version: int | None = None,
    ) -> StoredMatch:
        return replace(
            stored_match,
            state_payload=stored_match.state_payload if state_payload is None else state_payload,
            event_log_payloads=(
                stored_match.event_log_payloads
                if event_log_payloads is None
                else event_log_payloads
            ),
            staged_mulligans=(
                stored_match.staged_mulligans if staged_mulligans is None else staged_mulligans
            ),
            version=stored_match.version if version is None else version,
            updated_at=self._clock(),
        )

    def _rng_for_state_payload(self, state_payload: dict[str, object]) -> SupportsRandom | None:
        return self._rng_factory(
            state_rng_seed(state_payload),
            state_event_counter(state_payload),
        )


def _default_rng_factory(seed: int | None, event_counter: int) -> SupportsRandom | None:
    if seed is None:
        return None
    from gwent_service.engine.randomness import StdlibRandomAdapter

    return StdlibRandomAdapter(seed + event_counter)


def _utc_now() -> datetime:
    return datetime.now(UTC)
