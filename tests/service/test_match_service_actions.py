from gwent_engine.assets import load_card_registry
from gwent_engine.core import AbilityKind
from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO, CardInstanceId
from gwent_engine.core.state import GameState
from gwent_service.dto import (
    PassTurnCommand,
    PlayCardCommand,
    ResolveChoiceCommand,
    SubmitMulliganCommand,
)
from gwent_service.engine_adapter import GwentEngineAdapter
from gwent_service.match_service import snapshot_from_stored_match

from tests.service.support import (
    build_create_match_command,
    build_service,
    build_started_match,
    pending_decoy_state,
    replace_match_state,
)


def test_match_service_play_card_and_pass_flow_work_end_to_end() -> None:
    service, repository = build_started_match(
        match_id="action_match",
        alice_deck_id="monsters_muster_swarm_strict",
        bob_deck_id="monsters_muster_swarm_strict",
    )

    played_view = service.play_card(
        PlayCardCommand(
            match_id="action_match",
            service_player_id="alice",
            card_instance_id="p1_card_1",
            target_row="close",
        )
    )
    after_play = repository.get("action_match")
    assert after_play is not None
    assert len(played_view.viewer_hand) == 9
    assert played_view.viewer.rows.close[0].instance_id == "p1_card_1"
    assert len(after_play.event_log_payloads) == 7

    passed_view = service.pass_turn(
        PassTurnCommand(
            match_id="action_match",
            service_player_id="bob",
        )
    )
    after_pass = repository.get("action_match")
    assert after_pass is not None
    assert passed_view.viewer.has_passed is True
    assert passed_view.current_player == "p1"
    assert len(after_pass.event_log_payloads) == 8


def test_match_service_reloads_state_after_spy_is_played() -> None:
    service, repository = build_started_match(match_id="spy_match")
    adapter = GwentEngineAdapter()

    stored = repository.get("spy_match")
    assert stored is not None
    spy_card_id = _first_spy_in_hand(adapter.deserialize_state(stored.state_payload))

    _ = service.play_card(
        PlayCardCommand(
            match_id="spy_match",
            service_player_id="alice",
            card_instance_id="p1_card_1",
            target_row="close",
        )
    )
    _ = service.play_card(
        PlayCardCommand(
            match_id="spy_match",
            service_player_id="bob",
            card_instance_id=str(spy_card_id),
            target_row="close",
        )
    )

    after_spy = repository.get("spy_match")
    assert after_spy is not None
    snapshot = snapshot_from_stored_match(after_spy, adapter=adapter)
    spy = snapshot.state.card(spy_card_id)

    assert spy.owner == PLAYER_TWO
    assert spy.battlefield_side == PLAYER_ONE


def _first_spy_in_hand(state: GameState) -> CardInstanceId:
    card_registry = load_card_registry()
    for card_id in state.players[1].hand:
        definition = card_registry.get(state.card(card_id).definition_id)
        if AbilityKind.SPY in definition.ability_kinds:
            return card_id
    raise AssertionError("Expected a spy in the opponent's opening hand.")


def test_match_service_pending_choice_can_be_retrieved_and_resolved() -> None:
    service, repository = build_service()
    _ = service.create_match(
        build_create_match_command(
            match_id="pending_choice_match",
            alice_deck_id="scoiatael_high_stakes",
            bob_deck_id="scoiatael_high_stakes",
        ),
        viewer_service_player_id="alice",
    )
    _ = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="pending_choice_match",
            service_player_id="alice",
            card_instance_ids=("p1_card_9",),
        )
    )
    _ = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="pending_choice_match",
            service_player_id="bob",
            card_instance_ids=(),
        )
    )
    stored_match = repository.get("pending_choice_match")
    assert stored_match is not None
    pending_state = pending_decoy_state("pending_choice_match")
    _ = replace_match_state(repository, match_id="pending_choice_match", state=pending_state)

    pending_choice_view = service.get_match(
        "pending_choice_match", viewer_service_player_id="alice"
    )
    hidden_from_bob = service.get_match("pending_choice_match", viewer_service_player_id="bob")
    before_resolution = repository.get("pending_choice_match")

    assert before_resolution is not None
    assert pending_choice_view.pending_choice is not None
    assert hidden_from_bob.pending_choice is None
    assert len(before_resolution.event_log_payloads) == len(stored_match.event_log_payloads)

    resolved_view = service.resolve_choice(
        ResolveChoiceCommand(
            match_id="pending_choice_match",
            service_player_id="alice",
            choice_id=pending_choice_view.pending_choice.choice_id,
            selected_card_instance_ids=("p1_spy_target",),
        )
    )
    after_resolution = repository.get("pending_choice_match")

    assert after_resolution is not None
    assert resolved_view.pending_choice is None
    assert "p1_spy_target" in {card.instance_id for card in resolved_view.viewer_hand}
    assert len(after_resolution.event_log_payloads) > len(before_resolution.event_log_payloads)
