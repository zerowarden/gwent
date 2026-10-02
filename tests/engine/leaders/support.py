from gwent_engine.core.ids import CardInstanceId

from tests.engine.scenario_builder import ScenarioBuilder, card, scenario
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID

LEADER_RESERVE_CARD_ID = CardInstanceId("p1_leader_action_reserve")


def leader_scenario(name: str) -> ScenarioBuilder:
    return (
        scenario(name)
        .player(PLAYER_ONE_ID, hand=[card(LEADER_RESERVE_CARD_ID, "scoiatael_mahakaman_defender")])
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_leader_action_reserve", "scoiatael_mahakaman_defender")],
        )
    )
