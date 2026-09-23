from gwent_engine.ai.baseline.profile_catalog import DEFAULT_BASE_PROFILE
from gwent_engine.ai.policy import DEFAULT_SEARCH_CONFIG
from gwent_engine.ai.search.turn_resolution import TurnSearchResolver
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.ids import CardInstanceId

from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_search_candidate_samples_are_independent_of_prior_candidate_evaluation() -> None:
    state = (
        scenario("search_branch_randomness")
        .player(
            PLAYER_ONE_ID,
            faction="nilfgaard",
            leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
            hand=[
                card("p1_medic_a", "nilfgaard_etolian_auxilary_archer"),
                card("p1_medic_b", "nilfgaard_etolian_auxilary_archer"),
            ],
            discard=[
                card("p1_discard_catapult", "northern_realms_catapult"),
                card("p1_discard_archer", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_hidden_unit", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    resolver = TurnSearchResolver(
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    target_action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_medic_a"),
        target_row=Row.RANGED,
    )
    unrelated_stochastic_action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_medic_b"),
        target_row=Row.RANGED,
    )

    target_line = resolver.resolve_root_action_with_reply(state, target_action)
    _ = resolver.resolve_root_action_with_reply(state, unrelated_stochastic_action)
    repeated_target_line = resolver.resolve_root_action_with_reply(state, target_action)

    assert repeated_target_line == target_line
