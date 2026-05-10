from dataclasses import replace

from gwent_engine.ai.baseline.features import (
    dead_card_penalty,
    post_action_hand_value,
    projected_scorch_loss,
    projected_synergy_value,
    projected_weather_loss,
)
from gwent_engine.ai.policy import DEFAULT_FEATURE_POLICY
from gwent_engine.core import Row
from gwent_engine.core.ids import CardDefinitionId

from ..support import CARD_REGISTRY
from .test_baseline_support import make_player_assessment


def test_projected_scorch_loss_sums_the_removed_strength() -> None:
    assert (
        projected_scorch_loss(
            (4, 10, 10),
            threshold=DEFAULT_FEATURE_POLICY.scorch_threshold,
        )
        == 20
    )
    assert (
        projected_scorch_loss(
            (4, 9, 9),
            threshold=DEFAULT_FEATURE_POLICY.scorch_threshold,
        )
        == 0
    )


def test_projected_weather_loss_uses_row_summaries() -> None:
    player = make_player_assessment(player_id="p1")
    close = type(player.close)(Row.CLOSE, 2, 2, 9, 9)
    ranged = type(player.ranged)(Row.RANGED, 1, 1, 4, 4)
    siege = type(player.siege)(Row.SIEGE, 0, 0, 0, 0)
    player = replace(player, close=close, ranged=ranged, siege=siege)

    assert projected_weather_loss(player.row_summaries()) == 10


def test_post_action_hand_and_synergy_helpers_are_action_aware() -> None:
    remaining_hand = (
        CARD_REGISTRY.get(CardDefinitionId("northern_realms_blue_stripes_commando")),
        CARD_REGISTRY.get(CardDefinitionId("northern_realms_dun_banner_medic")),
    )
    board_definitions = (
        CARD_REGISTRY.get(CardDefinitionId("northern_realms_blue_stripes_commando")),
    )
    discard_definitions = (CARD_REGISTRY.get(CardDefinitionId("neutral_yennefer")),)

    assert post_action_hand_value(remaining_hand) == (
        CARD_REGISTRY.get(CardDefinitionId("northern_realms_blue_stripes_commando")).base_strength
        + CARD_REGISTRY.get(CardDefinitionId("northern_realms_dun_banner_medic")).base_strength
    )
    assert (
        projected_synergy_value(
            remaining_hand,
            board_definitions=board_definitions,
            discard_definitions=discard_definitions,
        )
        > 0
    )


def test_dead_card_penalty_counts_redundant_weather_and_clear_weather() -> None:
    definitions = (
        CARD_REGISTRY.get(CardDefinitionId("neutral_clear_weather")),
        CARD_REGISTRY.get(CardDefinitionId("neutral_biting_frost")),
    )

    assert dead_card_penalty(definitions) == 1
    assert dead_card_penalty(definitions, active_weather_rows=(Row.CLOSE,)) == 1
