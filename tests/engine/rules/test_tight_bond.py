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
    ("card_ids", "expected_strength", "expected_row_score"),
    [
        (("p1_first_bond_vanguard", "p1_second_bond_vanguard"), 8, 16),
        (
            (
                "p1_first_bond_vanguard",
                "p1_second_bond_vanguard",
                "p1_third_bond_vanguard",
            ),
            12,
            36,
        ),
    ],
)
def test_same_group_tight_bond_units_multiply_by_group_size(
    card_ids: tuple[str, ...],
    expected_strength: int,
    expected_row_score: int,
) -> None:
    bond_card_ids = tuple(CardInstanceId(card_id) for card_id in card_ids)
    state = (
        scenario(f"tight_bond_{len(bond_card_ids)}_cards")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[
                    card(card_id, "northern_realms_blue_stripes_commando")
                    for card_id in bond_card_ids
                ]
            ),
        )
        .build()
    )

    assert all(
        calculate_effective_strength(state, CARD_REGISTRY, card_id) == expected_strength
        for card_id in bond_card_ids
    )
    assert calculate_row_score(state, CARD_REGISTRY, PLAYER_ONE_ID, Row.CLOSE) == expected_row_score


def test_tight_bond_does_not_apply_across_rows() -> None:
    close_bond_card_id = CardInstanceId("p1_close_bond_vanguard")
    ranged_bond_card_id = CardInstanceId("p1_ranged_bond_ranger")
    state = (
        scenario("tight_bond_different_rows")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[card(close_bond_card_id, "northern_realms_blue_stripes_commando")],
                ranged=[card(ranged_bond_card_id, "northern_realms_crinfrid_reaver")],
            ),
        )
        .build()
    )

    assert calculate_effective_strength(state, CARD_REGISTRY, close_bond_card_id) == 4
    assert calculate_effective_strength(state, CARD_REGISTRY, ranged_bond_card_id) == 5


def test_tight_bond_does_not_apply_to_different_groups() -> None:
    vanguard_bond_card_id = CardInstanceId("p1_bond_vanguard")
    ballista_bond_card_id = CardInstanceId("p1_bond_ballista")
    state = (
        scenario("tight_bond_different_groups")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[
                    card(vanguard_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(ballista_bond_card_id, "northern_realms_catapult"),
                ]
            ),
        )
        .build()
    )

    assert calculate_effective_strength(state, CARD_REGISTRY, vanguard_bond_card_id) == 4
    assert calculate_effective_strength(state, CARD_REGISTRY, ballista_bond_card_id) == 8
    assert calculate_row_score(state, CARD_REGISTRY, PLAYER_ONE_ID, Row.CLOSE) == 12
