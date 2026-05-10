from gwent_engine.ai.actions import enumerate_mulligan_selections
from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.baseline.mulligan import choose_mulligan_selection
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.ids import CardInstanceId

from ..scenario_builder import card, scenario
from ..support import CARD_REGISTRY, PLAYER_ONE_ID


def test_choose_mulligan_selection_prefers_low_value_special_over_hero() -> None:
    state = (
        scenario("baseline_mulligan_state")
        .phase(Phase.MULLIGAN)
        .status(GameStatus.IN_PROGRESS)
        .player(
            "p1",
            hand=[
                card("p1_low_value_weather", "neutral_biting_frost"),
                card("p1_hero_finisher", "neutral_geralt"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)
    assessment = build_assessment(observation, CARD_REGISTRY)

    selection = choose_mulligan_selection(
        observation,
        legal_selections,
        assessment=assessment,
        card_registry=CARD_REGISTRY,
    )

    assert selection.cards_to_replace == (CardInstanceId("p1_low_value_weather"),)


def test_choose_mulligan_selection_can_keep_a_premium_hand() -> None:
    state = (
        scenario("baseline_mulligan_keep_state")
        .phase(Phase.MULLIGAN)
        .status(GameStatus.IN_PROGRESS)
        .player(
            "p1",
            hand=[
                card("p1_hero_finisher", "neutral_geralt"),
                card("p1_spy_unit", "nilfgaard_vattier_de_rideaux"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)
    assessment = build_assessment(observation, CARD_REGISTRY)

    selection = choose_mulligan_selection(
        observation,
        legal_selections,
        assessment=assessment,
        card_registry=CARD_REGISTRY,
    )

    assert selection.cards_to_replace == ()
