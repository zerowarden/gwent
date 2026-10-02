from dataclasses import replace

from gwent_engine.ai.agents import GreedyBot
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.baseline.bot import choose_mulligan_selection
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG
from gwent_engine.ai.turn_actions import enumerate_mulligan_selections
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.ids import CardInstanceId

from tests.support import PLAYER_ONE_ID

from ...scenario_builder import card, scenario
from ...support import CARD_REGISTRY


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

    selection = choose_mulligan_selection(
        observation,
        legal_selections,
        card_registry=CARD_REGISTRY,
        config=DEFAULT_BASELINE_CONFIG,
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

    selection = choose_mulligan_selection(
        observation,
        legal_selections,
        card_registry=CARD_REGISTRY,
        config=DEFAULT_BASELINE_CONFIG,
    )

    assert selection.cards_to_replace == ()


def test_configured_low_strength_anchor_changes_only_the_heuristic_mulligan() -> None:
    state = (
        scenario("baseline_mulligan_configured_anchor_state")
        .phase(Phase.MULLIGAN)
        .status(GameStatus.IN_PROGRESS)
        .player(
            "p1",
            hand=[
                card("p1_hero_finisher", "neutral_geralt"),
                card("p1_plain_unit", "neutral_vesemir"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)
    raised_anchor = replace(
        DEFAULT_BASELINE_CONFIG,
        mulligan=replace(DEFAULT_BASELINE_CONFIG.mulligan, low_strength_anchor=10),
    )

    def heuristic_selection(bot: HeuristicBot) -> tuple[CardInstanceId, ...]:
        selection = bot.choose_mulligan(observation, legal_selections, card_registry=CARD_REGISTRY)
        return selection.cards_to_replace

    greedy = GreedyBot().choose_mulligan(observation, legal_selections, card_registry=CARD_REGISTRY)

    assert heuristic_selection(HeuristicBot()) == ()
    assert heuristic_selection(HeuristicBot(config=raised_anchor)) == (
        CardInstanceId("p1_plain_unit"),
    )
    assert greedy.cards_to_replace == ()
