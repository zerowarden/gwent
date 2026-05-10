from dataclasses import replace

import pytest
from gwent_engine.core import Row, Zone
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.rules.scoring import (
    _row_score_context,  # pyright: ignore[reportPrivateUsage]
    calculate_effective_strength,
)

from tests.engine.primitives import PLAYER_ONE_ID, make_card_instance
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY


def test_non_battlefield_unit_uses_base_strength() -> None:
    card_registry = CARD_REGISTRY
    hand_griffin_card_id = CardInstanceId("p1_hand_griffin_base_strength")
    state = (
        scenario("non_battlefield_unit_uses_base_strength")
        .player(
            PLAYER_ONE_ID,
            hand=[card(hand_griffin_card_id, "monsters_griffin")],
        )
        .build()
    )

    assert calculate_effective_strength(state, card_registry, hand_griffin_card_id) == 5


def test_weathered_battlefield_unit_requires_battlefield_side() -> None:
    card_registry = CARD_REGISTRY
    battlefield_griffin_missing_side_card_id = make_card_instance(
        instance_id="p1_battlefield_griffin_missing_side_weather",
        definition_id="monsters_griffin",
        owner=PLAYER_ONE_ID,
        zone=Zone.BATTLEFIELD,
        row=Row.CLOSE,
    ).instance_id
    biting_frost_weather_card_id = make_card_instance(
        instance_id="neutral_biting_frost_weather_for_missing_side",
        definition_id="neutral_biting_frost",
        owner=PLAYER_ONE_ID,
        zone=Zone.WEATHER,
        row=Row.CLOSE,
    ).instance_id
    state = (
        scenario("weathered_battlefield_unit_requires_battlefield_side")
        .player(
            PLAYER_ONE_ID,
            board=rows(close=[card(battlefield_griffin_missing_side_card_id, "monsters_griffin")]),
        )
        .weather(rows(close=[card(biting_frost_weather_card_id, "neutral_biting_frost")]))
        .build()
    )
    state = replace(
        state,
        card_instances=(
            make_card_instance(
                instance_id=str(battlefield_griffin_missing_side_card_id),
                definition_id="monsters_griffin",
                owner=PLAYER_ONE_ID,
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
            ),
            state.card(biting_frost_weather_card_id),
        ),
    )

    with pytest.raises(ValueError, match=r"missing battlefield_side"):
        _ = calculate_effective_strength(
            state,
            card_registry,
            battlefield_griffin_missing_side_card_id,
        )


def test_battlefield_unit_requires_battlefield_side_for_post_weather_scoring() -> None:
    card_registry = CARD_REGISTRY
    battlefield_griffin_missing_side_card_id = make_card_instance(
        instance_id="p1_battlefield_griffin_missing_side_clear",
        definition_id="monsters_griffin",
        owner=PLAYER_ONE_ID,
        zone=Zone.BATTLEFIELD,
        row=Row.CLOSE,
    ).instance_id
    state = replace(
        scenario("battlefield_unit_requires_battlefield_side_for_post_weather_scoring")
        .player(
            PLAYER_ONE_ID,
            board=rows(close=[card(battlefield_griffin_missing_side_card_id, "monsters_griffin")]),
        )
        .build(),
        card_instances=(
            make_card_instance(
                instance_id="p1_battlefield_griffin_missing_side_clear",
                definition_id="monsters_griffin",
                owner=PLAYER_ONE_ID,
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
            ),
        ),
    )

    with pytest.raises(ValueError, match=r"missing battlefield_side"):
        _ = calculate_effective_strength(
            state,
            card_registry,
            battlefield_griffin_missing_side_card_id,
        )


def test_row_score_context_is_cached_per_state_and_registry_pair() -> None:
    card_registry = CARD_REGISTRY
    state = (
        scenario("row_score_context_is_cached")
        .player(
            PLAYER_ONE_ID,
            board=rows(close=[card("p1_close_griffin_cache", "monsters_griffin")]),
        )
        .build()
    )

    first = _row_score_context(state, card_registry, None)
    second = _row_score_context(state, card_registry, None)

    assert second is first
