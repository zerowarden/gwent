from gwent_engine.core import ChoiceSourceKind
from gwent_engine.serialize import game_state_to_dict
from gwent_service.application.commands import (
    ResolveChoiceCommand,
    SubmitMulliganCommand,
)
from gwent_service.domain.models import StoredMatch

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.service.support import build_create_match_command, build_service


def test_match_service_pending_choice_can_be_retrieved_and_resolved() -> None:
    service, repository = build_service()
    _ = service.create_match(
        build_create_match_command(
            match_id="pending_choice_match",
            alice_deck_id="scoiatael_high_stakes",
            bob_deck_id="scoiatael_high_stakes",
        ),
        viewer_service_player_id="alice",
    )
    _ = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="pending_choice_match",
            service_player_id="alice",
            card_instance_ids=("p1_card_9",),
        )
    )
    _ = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="pending_choice_match",
            service_player_id="bob",
            card_instance_ids=(),
        )
    )
    stored_match = repository.get("pending_choice_match")
    assert stored_match is not None
    pending_state = (
        scenario("pending_choice_match")
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_source_decoy", "neutral_decoy")],
            board=rows(ranged=[card("p1_spy_target", "scoiatael_dol_blathanna_archer")]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve_unit", "scoiatael_dol_blathanna_archer")],
        )
        .card_choice(
            choice_id="pending_choice_1",
            player_id=PLAYER_ONE_ID,
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_source_decoy",
            legal_target_card_instance_ids=("p1_spy_target",),
        )
        .build()
    )
    repository.update(
        StoredMatch(
            match_id=stored_match.match_id,
            state_payload=game_state_to_dict(pending_state),
            event_log_payloads=stored_match.event_log_payloads,
            player_slots=stored_match.player_slots,
            staged_mulligans=(),
            version=stored_match.version + 1,
            created_at=stored_match.created_at,
            updated_at=stored_match.updated_at,
        )
    )

    pending_choice_view = service.get_match(
        "pending_choice_match", viewer_service_player_id="alice"
    )
    hidden_from_bob = service.get_match("pending_choice_match", viewer_service_player_id="bob")
    before_resolution = repository.get("pending_choice_match")

    assert before_resolution is not None
    assert pending_choice_view.pending_choice is not None
    assert hidden_from_bob.pending_choice is None
    assert len(before_resolution.event_log_payloads) == len(stored_match.event_log_payloads)

    resolved_view = service.resolve_choice(
        ResolveChoiceCommand(
            match_id="pending_choice_match",
            service_player_id="alice",
            choice_id=pending_choice_view.pending_choice.choice_id,
            selected_card_instance_ids=("p1_spy_target",),
        )
    )
    after_resolution = repository.get("pending_choice_match")

    assert after_resolution is not None
    assert resolved_view.pending_choice is None
    assert "p1_spy_target" in {card.instance_id for card in resolved_view.viewer_hand}
    assert len(after_resolution.event_log_payloads) > len(before_resolution.event_log_payloads)
