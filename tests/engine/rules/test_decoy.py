from dataclasses import replace

import pytest
from gwent_engine.core import ChoiceSourceKind, Row, Zone
from gwent_engine.core.actions import PlayCardAction, ResolveChoiceAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_row_score

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY


def test_playing_decoy_creates_pending_choice_with_only_valid_targets() -> None:
    card_registry = CARD_REGISTRY
    valid_frontliner_card_id = CardInstanceId("p1_vanguard_frontliner")
    hero_frontliner_card_id = CardInstanceId("p1_hero_iorveth")
    friendly_special_card_id = CardInstanceId("p1_close_horn_special")
    opposing_unit_card_id = CardInstanceId("p2_opposing_archer")
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    state = (
        scenario("decoy_creates_pending_choice")
        .player(
            PLAYER_ONE_ID,
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(
                close=[
                    card(valid_frontliner_card_id, "scoiatael_mahakaman_defender"),
                    card(hero_frontliner_card_id, "neutral_geralt"),
                    card(friendly_special_card_id, "neutral_commanders_horn"),
                ]
            ),
        )
        .player(
            PLAYER_TWO_ID,
            board=rows(ranged=[card(opposing_unit_card_id, "scoiatael_dol_blathanna_archer")]),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=card_registry,
    )

    assert events == ()
    assert next_state.pending_choice is not None
    assert next_state.pending_choice.source_kind == ChoiceSourceKind.DECOY
    assert next_state.pending_choice.source_card_instance_id == decoy_card_id
    assert next_state.pending_choice.legal_target_card_instance_ids == (valid_frontliner_card_id,)
    assert next_state.current_player == PLAYER_ONE_ID
    assert next_state.card(decoy_card_id).zone == Zone.HAND
    assert next_state.player(PLAYER_ONE_ID).rows.close == (
        valid_frontliner_card_id,
        hero_frontliner_card_id,
        friendly_special_card_id,
    )


def test_resolving_decoy_choice_swaps_cards_and_advances_turn() -> None:
    card_registry = CARD_REGISTRY
    frontliner_card_id = CardInstanceId("p1_vanguard_frontliner")
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    state = (
        scenario("resolving_decoy_choice_swaps_cards")
        .player(
            PLAYER_ONE_ID,
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(close=[card(frontliner_card_id, "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    pending_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=card_registry,
    )
    assert pending_state.pending_choice is not None

    resolved_state, events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(frontliner_card_id,),
        ),
        card_registry=card_registry,
    )

    assert resolved_state.pending_choice is None
    assert resolved_state.player(PLAYER_ONE_ID).rows.close == (decoy_card_id,)
    assert resolved_state.card(decoy_card_id).zone == Zone.BATTLEFIELD
    assert resolved_state.card(decoy_card_id).row == Row.CLOSE
    assert resolved_state.card(frontliner_card_id).zone == Zone.HAND
    assert resolved_state.card(frontliner_card_id).row is None
    assert frontliner_card_id in resolved_state.player(PLAYER_ONE_ID).hand
    assert resolved_state.current_player == PLAYER_TWO_ID
    assert calculate_row_score(resolved_state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 0
    assert isinstance(events[1], SpecialCardResolvedEvent)
    assert events[1].target_card_instance_id == frontliner_card_id


def test_decoy_is_illegal_without_any_valid_target() -> None:
    card_registry = CARD_REGISTRY
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    state = (
        scenario("decoy_is_illegal_without_valid_target")
        .player(
            PLAYER_ONE_ID,
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(close=[card("p1_close_horn_special", "neutral_commanders_horn")]),
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="valid non-hero unit card"):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PLAYER_ONE_ID,
                card_instance_id=decoy_card_id,
            ),
            card_registry=card_registry,
        )


def test_decoy_can_target_spy_on_your_battlefield_regardless_of_original_owner() -> None:
    card_registry = CARD_REGISTRY
    opponent_owned_spy_card_id = CardInstanceId("p2_spy_vattier_on_p1_side")
    opponent_reserve_card_id = CardInstanceId("p2_reserve_archer_card")
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    state = (
        scenario("decoy_can_target_spy_on_your_side")
        .current_player(PLAYER_ONE_ID)
        .player(
            PLAYER_ONE_ID,
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(
                close=[
                    card(
                        opponent_owned_spy_card_id,
                        "nilfgaard_vattier_de_rideaux",
                        owner=PLAYER_TWO_ID,
                    )
                ]
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(opponent_reserve_card_id, "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    pending_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=card_registry,
    )

    assert events == ()
    assert pending_state.pending_choice is not None
    assert pending_state.pending_choice.legal_target_card_instance_ids == (
        opponent_owned_spy_card_id,
    )

    resolved_state, _ = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(opponent_owned_spy_card_id,),
        ),
        card_registry=card_registry,
    )

    returned_spy = resolved_state.card(opponent_owned_spy_card_id)
    assert returned_spy.zone == Zone.HAND
    assert returned_spy.owner == PLAYER_ONE_ID
    assert opponent_owned_spy_card_id in resolved_state.player(PLAYER_ONE_ID).hand
    assert resolved_state.player(PLAYER_ONE_ID).rows.close == (decoy_card_id,)

    replay_ready_state = replace(resolved_state, current_player=PLAYER_ONE_ID)

    replayed_state, _ = apply_action(
        replay_ready_state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=opponent_owned_spy_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert replayed_state.card(opponent_owned_spy_card_id).battlefield_side == PLAYER_TWO_ID
