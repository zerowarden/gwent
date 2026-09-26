from gwent_engine.core import AbilityKind
from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO, CardInstanceId
from gwent_engine.core.state import GameState
from gwent_engine.runtime_assets import load_card_registry
from gwent_service.application.commands import PassTurnCommand, PlayCardCommand
from gwent_service.application.snapshot import snapshot_from_stored_match
from gwent_service.engine.adapter import GwentEngineAdapter

from tests.service.support import (
    build_started_match,
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
