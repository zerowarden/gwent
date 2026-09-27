import pytest
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import MusterResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_effective_strength, calculate_row_score

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
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


@pytest.mark.parametrize(
    "definition_id",
    [
        "nilfgaard_impera_brigade_guard",
        "nilfgaard_nausicaa_cavalry_rider",
        "nilfgaard_young_emissary",
    ],
)
def test_nilfgaard_bond_units_do_not_muster_other_copies(definition_id: str) -> None:
    played_id = CardInstanceId("p1_played_bond_unit")
    held_id = CardInstanceId("p1_held_bond_unit")
    deck_id = CardInstanceId("p1_deck_bond_unit")
    state = (
        scenario("nilfgaard_bond_units_do_not_muster")
        .player(
            PLAYER_ONE_ID,
            hand=[card(played_id, definition_id), card(held_id, definition_id)],
            deck=[card(deck_id, definition_id)],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=played_id,
            target_row=Row.CLOSE,
        ),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.close == (played_id,)
    assert next_state.player(PLAYER_ONE_ID).hand == (held_id,)
    assert next_state.player(PLAYER_ONE_ID).deck == (deck_id,)
    assert not any(isinstance(event, MusterResolvedEvent) for event in events)


@pytest.mark.parametrize(
    ("definition_id", "copies", "expected_row_score"),
    [
        ("nilfgaard_impera_brigade_guard", 4, 48),
        ("nilfgaard_nausicaa_cavalry_rider", 2, 8),
        ("nilfgaard_young_emissary", 2, 20),
    ],
)
def test_nilfgaard_bond_families_multiply_when_played_together(
    definition_id: str,
    copies: int,
    expected_row_score: int,
) -> None:
    state = (
        scenario("nilfgaard_bond_family_score")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[card(f"p1_bond_unit_{index}", definition_id) for index in range(copies)]
            ),
        )
        .build()
    )

    assert calculate_row_score(state, CARD_REGISTRY, PLAYER_ONE_ID, Row.CLOSE) == expected_row_score
