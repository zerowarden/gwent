from __future__ import annotations

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.profile_catalog import DEFAULT_BASE_PROFILE
from gwent_engine.ai.observations import (
    ObservedCard,
    ObservedDeckEntry,
    ObservedLeader,
    ObservedRows,
    PlayerObservation,
    PublicGameStateView,
    PublicPlayerStateView,
    build_player_observation,
)
from gwent_engine.ai.policy import DEFAULT_SEARCH_CONFIG
from gwent_engine.ai.search import build_search_engine
from gwent_engine.ai.search.simulation import (
    SIMULATION_HIDDEN_CARD_DEFINITION,
    materialize_player_simulation,
)
from gwent_engine.ai.search.types import SearchResult
from gwent_engine.cards import CardRegistry
from gwent_engine.core import FactionId, GameStatus, Phase, Row
from gwent_engine.core.actions import (
    PlayCardAction,
)
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    GameId,
    LeaderId,
)
from gwent_engine.core.state import GameState

from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
)


def _manual_observation() -> PlayerObservation:
    return PlayerObservation(
        viewer_player_id=PLAYER_ONE_ID,
        public_state=PublicGameStateView(
            game_id=GameId("manual_observation"),
            phase=Phase.IN_ROUND,
            status=GameStatus.IN_PROGRESS,
            current_player=PLAYER_ONE_ID,
            starting_player=PLAYER_ONE_ID,
            round_starter=PLAYER_ONE_ID,
            round_number=1,
            match_winner=None,
            players=(
                PublicPlayerStateView(
                    player_id=PLAYER_ONE_ID,
                    faction=FactionId.SCOIATAEL,
                    leader=ObservedLeader(
                        leader_id=LeaderId("scoiatael_francesca_the_beautiful"),
                        used=False,
                        disabled=False,
                        horn_row=None,
                    ),
                    deck_count=1,
                    hand_count=1,
                    discard=(),
                    rows=ObservedRows(),
                    gems_remaining=2,
                    round_wins=0,
                    has_passed=False,
                ),
                PublicPlayerStateView(
                    player_id=PLAYER_TWO_ID,
                    faction=FactionId.NILFGAARD,
                    leader=ObservedLeader(
                        leader_id=LeaderId("nilfgaard_emhyr_the_white_flame"),
                        used=False,
                        disabled=False,
                        horn_row=None,
                    ),
                    deck_count=2,
                    hand_count=1,
                    discard=(),
                    rows=ObservedRows(),
                    gems_remaining=2,
                    round_wins=0,
                    has_passed=False,
                ),
            ),
            battlefield_weather=ObservedRows(),
            pending_choice=None,
        ),
        viewer_hand=(
            ObservedCard(
                instance_id=CardInstanceId("viewer_archer"),
                definition_id=CardDefinitionId("scoiatael_dol_blathanna_archer"),
                owner=PLAYER_ONE_ID,
            ),
        ),
        viewer_deck_composition=(
            ObservedDeckEntry(
                definition_id=CardDefinitionId("neutral_geralt"),
                instance_ids=(CardInstanceId("viewer_deck_geralt"),),
            ),
        ),
        visible_pending_choice=None,
    )


def test_search_engine_runs_from_observation_without_source_state() -> None:
    observation = _manual_observation()
    legal_actions = (
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("viewer_archer"),
            target_row=Row.RANGED,
        ),
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert result.used_fallback_policy is False
    assert result.chosen_action == legal_actions[0]
    assert result.principal_line is not None


def test_search_materializes_without_incidental_catalog_placeholder() -> None:
    state = (
        scenario("search_custom_registry")
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_hidden_unit", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_trebuchet")],
        )
        .build()
    )
    custom_registry = CardRegistry.from_definitions(
        definition
        for definition in CARD_REGISTRY
        if definition.definition_id != CardDefinitionId("scoiatael_mahakaman_defender")
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    simulation = materialize_player_simulation(
        observation,
        card_registry=custom_registry,
    )
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="custom_registry_search",
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=custom_registry,
        leader_registry=LEADER_REGISTRY,
    )

    assert SIMULATION_HIDDEN_CARD_DEFINITION.definition_id in simulation.card_registry
    assert simulation.state.card(CardInstanceId("opponent_hidden_hand_001")).definition_id == (
        SIMULATION_HIDDEN_CARD_DEFINITION.definition_id
    )
    assert result.used_fallback_policy is False


def test_search_engine_ignores_opponent_hidden_hand_and_deck_identities() -> None:
    state_a = (
        scenario("search_public_info_invariance")
        .player(
            "p1",
            hand=[
                card("p1_catapult", "northern_realms_catapult"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
            board=rows(siege=[card("p1_trebuchet", "northern_realms_trebuchet")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
            hand=[card("p2_hidden_a", "neutral_geralt")],
            deck=[card("p2_deck_a", "northern_realms_catapult")],
            board=rows(siege=[card("p2_catapult", "northern_realms_catapult")]),
        )
        .build()
    )
    state_b = (
        scenario("search_public_info_invariance_alt")
        .player(
            "p1",
            hand=[
                card("p1_catapult", "northern_realms_catapult"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
            board=rows(siege=[card("p1_trebuchet", "northern_realms_trebuchet")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
            hand=[card("p2_hidden_other", "neutral_mysterious_elf")],
            deck=[card("p2_deck_other", "skellige_kambi")],
            board=rows(siege=[card("p2_catapult", "northern_realms_catapult")]),
        )
        .build()
    )

    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )

    def choose(state_name: str, state_obj: GameState) -> SearchResult:
        observation = build_player_observation(state_obj, PLAYER_ONE_ID, LEADER_REGISTRY)
        legal_actions = enumerate_legal_actions(
            state_obj,
            player_id=PLAYER_ONE_ID,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
        result = engine.choose_action(
            observation,
            legal_actions,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
        assert result.principal_line is not None, state_name
        return result

    result_a = choose("state_a", state_a)
    result_b = choose("state_b", state_b)

    assert result_a.chosen_action == result_b.chosen_action
    assert result_a.principal_line is not None
    assert result_b.principal_line is not None
    assert result_a.principal_line.reply_actions == result_b.principal_line.reply_actions
