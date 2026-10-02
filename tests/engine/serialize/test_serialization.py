from dataclasses import replace

import pytest
from gwent_engine.core import (
    Row,
)
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import InvariantError
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import PendingAvengerSummon
from gwent_engine.serialize import (
    game_state_from_dict,
    game_state_to_dict,
)

from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY, run_scripted_round
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


def test_game_state_serialization_roundtrip() -> None:
    final_state, _ = run_scripted_round()
    roundtrip_state = game_state_from_dict(game_state_to_dict(replace(final_state, rng_seed=123)))

    assert roundtrip_state == replace(final_state, rng_seed=123)


def test_game_state_serialization_roundtrip_with_pending_avenger_summon() -> None:
    final_state, _ = run_scripted_round()
    queued_source_card_id = final_state.player(PLAYER_ONE_ID).discard[0]
    pending_state = replace(
        final_state,
        pending_avenger_summons=(
            PendingAvengerSummon(
                source_card_instance_id=queued_source_card_id,
                summoned_definition_id=CardDefinitionId("neutral_bovine_defense_force"),
                owner=PLAYER_ONE_ID,
                battlefield_side=PLAYER_ONE_ID,
                row=Row.RANGED,
            ),
        ),
        generated_card_counter=2,
        rng_seed=321,
    )

    assert game_state_from_dict(game_state_to_dict(pending_state)) == pending_state


def test_game_state_serialization_roundtrip_with_pending_choice() -> None:
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    frontliner_card_id = CardInstanceId("p1_vanguard_frontliner")
    pending_state, _ = apply_action(
        scenario("serialization_roundtrip_with_pending_choice")
        .player(
            PLAYER_ONE_ID,
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(close=[card(frontliner_card_id, "scoiatael_mahakaman_defender")]),
        )
        .build(),
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=CARD_REGISTRY,
    )

    assert pending_state.pending_choice is not None
    assert game_state_from_dict(game_state_to_dict(pending_state)) == pending_state


def test_game_state_serialization_roundtrip_with_battlefield_weather() -> None:
    weathered_state = (
        scenario("serialization_roundtrip_with_battlefield_weather")
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_reserve_card", "scoiatael_mahakaman_defender")],
        )
        .weather(
            rows(
                close=[card("p1_biting_frost_weather", "neutral_biting_frost")],
                ranged=[card("p2_impenetrable_fog_weather", "neutral_impenetrable_fog")],
            )
        )
        .build()
    )

    roundtrip_state = game_state_from_dict(game_state_to_dict(weathered_state))

    assert roundtrip_state == weathered_state
    assert roundtrip_state.weather == weathered_state.weather


def test_game_state_serialization_roundtrip_with_opponent_side_spy() -> None:
    spy_state = (
        scenario("serialization_roundtrip_with_opponent_side_spy")
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_reserve_card", "scoiatael_mahakaman_defender")],
            board=rows(
                close=[
                    card(
                        "p2_spy",
                        "nilfgaard_shilard_fitz_oesterlen",
                        owner=PLAYER_TWO_ID,
                    )
                ]
            ),
        )
        .build()
    )
    payload = game_state_to_dict(spy_state)

    with pytest.raises(InvariantError, match="belongs to"):
        _ = game_state_from_dict(payload)

    roundtrip_state = game_state_from_dict(payload, card_registry=CARD_REGISTRY)

    assert roundtrip_state == spy_state


def test_game_state_serialization_rejects_opponent_side_non_spy() -> None:
    intruder_state = (
        scenario("serialization_rejects_opponent_side_non_spy")
        .player(
            PLAYER_ONE_ID,
            board=rows(close=[card("p2_intruder", "nilfgaard_vreemde", owner=PLAYER_TWO_ID)]),
        )
        .build()
    )

    with pytest.raises(InvariantError, match="belongs to"):
        _ = game_state_from_dict(
            game_state_to_dict(intruder_state),
            card_registry=CARD_REGISTRY,
        )
