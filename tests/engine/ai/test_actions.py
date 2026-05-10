from gwent_engine.ai.actions import (
    action_to_id,
    enumerate_legal_actions,
    enumerate_mulligan_selections,
    legal_action_mask,
)
from gwent_engine.ai.turn_actions import enumerate_candidate_actions
from gwent_engine.core import ChoiceKind, ChoiceSourceKind, Row
from gwent_engine.core.actions import PlayCardAction, ResolveChoiceAction
from gwent_engine.core.ids import CardInstanceId, ChoiceId, PlayerId

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
    build_sample_game_state,
    build_started_game_state,
)


def test_enumerate_legal_actions_returns_stable_unique_ids() -> None:
    state = (
        scenario("legal_actions_stable_ids")
        .player(
            "p1",
            hand=[
                card("p1_close_unit_card", "scoiatael_mahakaman_defender"),
                card("p1_weather_fog_card", "neutral_impenetrable_fog"),
            ],
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )
    repeated_ids = tuple(
        action_to_id(action)
        for action in enumerate_legal_actions(
            state,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
            player_id=PLAYER_ONE_ID,
        )
    )
    legal_action_ids = tuple(action_to_id(action) for action in legal_actions)

    assert legal_action_ids == repeated_ids
    assert len(set(legal_action_ids)) == len(legal_action_ids)
    assert any(isinstance(action, PlayCardAction) for action in legal_actions)


def test_pending_choice_enumeration_returns_only_resolution_actions() -> None:
    state = (
        scenario("pending_choice_resolution_actions")
        .player(
            "p1",
            hand=[card("p1_decoy_trick_card", "neutral_decoy")],
            board=rows(
                close=[card("p1_target_a", "scoiatael_mahakaman_defender")],
                ranged=[card("p1_target_b", "scoiatael_dol_blathanna_archer")],
            ),
        )
        .pending_choice(
            choice_id="choice_1",
            player_id="p1",
            kind=ChoiceKind.SELECT_CARD_INSTANCE,
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_decoy_trick_card",
            legal_target_card_instance_ids=("p1_target_a", "p1_target_b"),
        )
        .build()
    )

    legal_actions = enumerate_legal_actions(state, player_id=PLAYER_ONE_ID)

    assert legal_actions == (
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=ChoiceId("choice_1"),
            selected_card_instance_ids=(CardInstanceId("p1_target_a"),),
        ),
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=ChoiceId("choice_1"),
            selected_card_instance_ids=(CardInstanceId("p1_target_b"),),
        ),
    )


def test_legal_action_mask_marks_illegal_candidates_as_zero() -> None:
    close_unit_card_id = CardInstanceId("p1_close_unit_card")
    state = (
        scenario("legal_action_mask")
        .player(
            "p1",
            hand=[card(close_unit_card_id, "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    legal_actions = enumerate_legal_actions(
        state,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )
    illegal_action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=close_unit_card_id,
        target_row=Row.SIEGE,
    )

    assert legal_action_mask((*legal_actions, illegal_action), legal_actions)[-1] == 0


def test_enumerate_mulligan_selections_covers_empty_and_single_card_options() -> None:
    state, _ = build_started_game_state()
    selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)

    assert selections[0].cards_to_replace == ()
    assert any(len(selection.cards_to_replace) == 1 for selection in selections)


def test_enumerate_candidate_actions_rejects_unknown_start_phase_player() -> None:
    state = build_sample_game_state()

    assert (
        enumerate_candidate_actions(
            state,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
            player_id=PlayerId("ghost"),
        )
        == ()
    )
