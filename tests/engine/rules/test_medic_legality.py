import pytest
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError

from tests.engine.rules.support import assert_play_rejected, play_action, validate_play
from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
)
from tests.support import IdentityRandom


def test_medic_legality_requires_rng_for_randomized_restore_leader() -> None:
    state = (
        scenario("legality_randomized_medic_requires_rng")
        .player(
            "p1",
            faction="nilfgaard",
            leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[card("p1_archer_in_discard", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="requires an injected RNG"):
        validate_play(
            state,
            play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
            rng=None,
        )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (
            play_action(
                "p1_field_surgeon_in_hand",
                target_row=Row.RANGED,
                target_card_instance_id="p1_archer_in_discard",
            ),
            "do not allow explicit Medic targets",
        ),
    ],
)
def test_randomized_medic_legality_rejects_explicit_targets(
    action: PlayCardAction,
    message: str,
) -> None:
    assert_play_rejected(
        scenario_name="legality_randomized_medic_reject_explicit_targets",
        faction="nilfgaard",
        leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
        hand_card_instance_id="p1_field_surgeon_in_hand",
        hand_card_definition_id="scoiatael_havekar_healer",
        discard_card_instance_id="p1_archer_in_discard",
        discard_card_definition_id="scoiatael_dol_blathanna_archer",
        action=action,
        message=message,
        rng=IdentityRandom(),
    )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (
            play_action(
                "p1_field_surgeon_in_hand",
                target_row=Row.RANGED,
                target_card_instance_id="p1_archer_in_discard",
            ),
            "Medic discard targets are resolved through pending choice.",
        ),
    ],
)
def test_pending_choice_medic_legality_rejects_explicit_targets(
    action: PlayCardAction,
    message: str,
) -> None:
    assert_play_rejected(
        scenario_name="legality_pending_choice_medic_reject_explicit_targets",
        hand_card_instance_id="p1_field_surgeon_in_hand",
        hand_card_definition_id="scoiatael_havekar_healer",
        discard_card_instance_id="p1_archer_in_discard",
        discard_card_definition_id="scoiatael_dol_blathanna_archer",
        action=action,
        message=message,
    )


def test_medic_legality_allows_play_without_valid_resurrection_target() -> None:
    state = (
        scenario("legality_medic_requires_non_hero_unit")
        .player(
            "p1",
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[
                card("p1_iorveth_hero_in_discard", "neutral_geralt"),
                card("p1_decoy_special_in_discard", "neutral_decoy"),
            ],
        )
        .build()
    )

    validate_play(
        state,
        play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
    )


def test_medic_legality_accepts_pending_choice_with_valid_discard_target() -> None:
    state = (
        scenario("legality_medic_accepts_valid_discard_target")
        .player(
            "p1",
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[card("p1_archer_in_discard", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    validate_play(
        state,
        play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
    )


def test_randomized_medic_legality_accepts_rng_driven_restore() -> None:
    state = (
        scenario("legality_randomized_medic_accepts_rng_restore")
        .player(
            "p1",
            faction="nilfgaard",
            leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
            hand=[card("p1_field_surgeon_in_hand", "scoiatael_havekar_healer")],
            discard=[card("p1_archer_in_discard", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    validate_play(
        state,
        play_action("p1_field_surgeon_in_hand", target_row=Row.RANGED),
        rng=IdentityRandom(),
    )
