import pytest
from gwent_engine.core import Row
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.rules.scoring import calculate_effective_strength, calculate_row_score

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
)


@pytest.mark.parametrize(
    (
        "morale_card_ids",
        "expected_morale_strength",
        "expected_vanguard_strength",
        "expected_row_score",
    ),
    [
        (("p1_standard_bearer",), 1, 6, 7),
        (("p1_first_standard_bearer", "p1_second_standard_bearer"), 2, 7, 11),
    ],
)
def test_morale_boost_adds_one_to_other_units_and_stacks(
    morale_card_ids: tuple[str, ...],
    expected_morale_strength: int,
    expected_vanguard_strength: int,
    expected_row_score: int,
) -> None:
    morale_ids = tuple(CardInstanceId(card_id) for card_id in morale_card_ids)
    vanguard_card_id = CardInstanceId("p1_vanguard_frontliner")
    state = (
        scenario(f"morale_boost_{len(morale_ids)}")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[
                    *(
                        card(morale_id, "northern_realms_kaedweni_siege_expert")
                        for morale_id in morale_ids
                    ),
                    card(vanguard_card_id, "scoiatael_mahakaman_defender"),
                ]
            ),
        )
        .build()
    )

    assert all(
        calculate_effective_strength(state, CARD_REGISTRY, morale_id) == expected_morale_strength
        for morale_id in morale_ids
    )
    assert calculate_effective_strength(state, CARD_REGISTRY, vanguard_card_id) == (
        expected_vanguard_strength
    )
    assert calculate_row_score(state, CARD_REGISTRY, PLAYER_ONE_ID, Row.CLOSE) == (
        expected_row_score
    )
