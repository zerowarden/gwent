import pytest
from gwent_engine.core import (
    ChoiceKind,
    ChoiceSourceKind,
    FactionId,
    GameStatus,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.errors import (
    IllegalActionError,
    InvariantError,
    UnknownCardInstanceError,
    UnknownPlayerError,
)
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    PlayerId,
)
from gwent_engine.core.invariants import check_game_state_invariants
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    LeaderState,
    PendingChoice,
    PlayerState,
    RowState,
)

from tests.engine.scenario_builder import scenario
from tests.engine.support import (
    CARD_REGISTRY,
    build_in_round_game_state,
    build_sample_game_state,
    build_started_game_state,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


def test_basic_runtime_invariants_pass_for_valid_state() -> None:
    state = _build_valid_state()

    check_game_state_invariants(state)


def test_invariants_fail_when_card_zone_disagrees_with_container() -> None:
    state = _build_valid_state(
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("card_1"),
                definition_id=CardDefinitionId("monsters_griffin"),
                owner=PLAYER_ONE_ID,
                zone=Zone.HAND,
            ),
        )
    )

    with pytest.raises(InvariantError, match="zone"):
        check_game_state_invariants(state)


def test_invariants_fail_when_current_player_has_already_passed() -> None:
    player_one = PlayerState(
        player_id=PLAYER_ONE_ID,
        faction=FactionId.MONSTERS,
        leader=LeaderState(leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders")),
        deck=(),
        hand=(CardInstanceId("card_1"),),
        discard=(),
        rows=RowState(),
        has_passed=True,
    )
    player_two = PlayerState(
        player_id=PLAYER_TWO_ID,
        faction=FactionId.NILFGAARD,
        leader=LeaderState(leader_id=LeaderId("nilfgaard_emhyr_his_imperial_majesty")),
        deck=(),
        hand=(),
        discard=(),
        rows=RowState(),
    )
    state = GameState(
        game_id=GameId("game_1"),
        players=(player_one, player_two),
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("card_1"),
                definition_id=CardDefinitionId("monsters_griffin"),
                owner=PLAYER_ONE_ID,
                zone=Zone.HAND,
            ),
        ),
        current_player=PLAYER_ONE_ID,
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
    )

    with pytest.raises(InvariantError, match="current player"):
        check_game_state_invariants(state)


def test_invariants_allow_empty_handed_current_player() -> None:
    # An empty hand does not end a round: an unused active leader still counts
    # as an action, and PlayerState alone cannot decide continuation.
    state = scenario("empty_handed_current_player").build()

    check_game_state_invariants(state)


def test_spy_card_may_live_on_the_opponent_battlefield_side() -> None:
    state = GameState(
        game_id=GameId("game_1"),
        players=(
            PlayerState(
                player_id=PLAYER_ONE_ID,
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(),
                rows=RowState(),
            ),
            PlayerState(
                player_id=PLAYER_TWO_ID,
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(),
                rows=RowState(close=(CardInstanceId("p1_spy_infiltrator"),)),
            ),
        ),
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("p1_spy_infiltrator"),
                definition_id=CardDefinitionId("northern_realms_prince_stennis"),
                owner=PLAYER_ONE_ID,
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
                battlefield_side=PLAYER_TWO_ID,
            ),
        ),
        current_player=None,
        starting_player=PLAYER_ONE_ID,
        round_starter=PLAYER_ONE_ID,
        phase=Phase.ROUND_RESOLUTION,
        status=GameStatus.IN_PROGRESS,
    )

    check_game_state_invariants(state, card_registry=CARD_REGISTRY)


def test_non_spy_card_cannot_live_on_the_opponent_battlefield_side() -> None:
    state = GameState(
        game_id=GameId("game_1"),
        players=(
            PlayerState(
                player_id=PLAYER_ONE_ID,
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(),
                rows=RowState(),
            ),
            PlayerState(
                player_id=PLAYER_TWO_ID,
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(),
                rows=RowState(close=(CardInstanceId("p1_vanguard_frontliner"),)),
            ),
        ),
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("p1_vanguard_frontliner"),
                definition_id=CardDefinitionId("scoiatael_mahakaman_defender"),
                owner=PLAYER_ONE_ID,
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
                battlefield_side=PLAYER_TWO_ID,
            ),
        ),
        current_player=PLAYER_ONE_ID,
        starting_player=PLAYER_ONE_ID,
        round_starter=PLAYER_ONE_ID,
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
    )

    with pytest.raises(InvariantError, match="belongs to"):
        check_game_state_invariants(state, card_registry=CARD_REGISTRY)


def test_ended_match_may_skip_completed_mulligans_when_player_left_early() -> None:
    player_one = PlayerState(
        player_id=PLAYER_ONE_ID,
        faction=FactionId.MONSTERS,
        leader=LeaderState(leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders")),
        deck=(CardInstanceId("card_1"),),
        hand=(),
        discard=(),
        rows=RowState(),
        gems_remaining=0,
    )
    player_two = PlayerState(
        player_id=PLAYER_TWO_ID,
        faction=FactionId.NILFGAARD,
        leader=LeaderState(leader_id=LeaderId("nilfgaard_emhyr_his_imperial_majesty")),
        deck=(),
        hand=(),
        discard=(),
        rows=RowState(),
    )
    state = GameState(
        game_id=GameId("game_1"),
        players=(player_one, player_two),
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("card_1"),
                definition_id=CardDefinitionId("monsters_griffin"),
                owner=PLAYER_ONE_ID,
                zone=Zone.DECK,
            ),
        ),
        phase=Phase.MATCH_ENDED,
        status=GameStatus.MATCH_ENDED,
        match_winner=PLAYER_TWO_ID,
    )

    check_game_state_invariants(state)


def test_pending_choice_source_card_must_remain_in_hand_until_resolution() -> None:
    state = GameState(
        game_id=GameId("game_1"),
        players=(
            PlayerState(
                player_id=PLAYER_ONE_ID,
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(CardInstanceId("p1_decoy_trick_card"),),
                rows=RowState(close=(CardInstanceId("p1_vanguard_frontliner"),)),
            ),
            PlayerState(
                player_id=PLAYER_TWO_ID,
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(),
                rows=RowState(),
            ),
        ),
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("p1_decoy_trick_card"),
                definition_id=CardDefinitionId("scoiatael_decoy"),
                owner=PLAYER_ONE_ID,
                zone=Zone.DISCARD,
            ),
            CardInstance(
                instance_id=CardInstanceId("p1_vanguard_frontliner"),
                definition_id=CardDefinitionId("scoiatael_vanguard"),
                owner=PLAYER_ONE_ID,
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
                battlefield_side=PLAYER_ONE_ID,
            ),
        ),
        pending_choice=PendingChoice(
            choice_id=ChoiceId("decoy_choice"),
            player_id=PLAYER_ONE_ID,
            kind=ChoiceKind.SELECT_CARD_INSTANCE,
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id=CardInstanceId("p1_decoy_trick_card"),
            legal_target_card_instance_ids=(CardInstanceId("p1_vanguard_frontliner"),),
        ),
        current_player=PLAYER_ONE_ID,
        starting_player=PLAYER_ONE_ID,
        round_starter=PLAYER_ONE_ID,
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
    )

    with pytest.raises(InvariantError, match="remain in hand"):
        check_game_state_invariants(state)


def _build_valid_state(
    *,
    card_instances: tuple[CardInstance, ...] | None = None,
) -> GameState:
    player_one = PlayerState(
        player_id=PLAYER_ONE_ID,
        faction=FactionId.MONSTERS,
        leader=LeaderState(leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders")),
        deck=(CardInstanceId("card_1"),),
        hand=(),
        discard=(),
        rows=RowState(),
    )
    player_two = PlayerState(
        player_id=PLAYER_TWO_ID,
        faction=FactionId.NILFGAARD,
        leader=LeaderState(leader_id=LeaderId("nilfgaard_emhyr_his_imperial_majesty")),
        deck=(),
        hand=(),
        discard=(),
        rows=RowState(),
    )
    return GameState(
        game_id=GameId("game_1"),
        players=(player_one, player_two),
        card_instances=card_instances
        or (
            CardInstance(
                instance_id=CardInstanceId("card_1"),
                definition_id=CardDefinitionId("monsters_griffin"),
                owner=PLAYER_ONE_ID,
                zone=Zone.DECK,
            ),
        ),
        phase=Phase.NOT_STARTED,
        status=GameStatus.NOT_STARTED,
    )


def test_state_card_and_player_lookup_use_indexed_access() -> None:
    state = build_sample_game_state()
    player = state.players[0]
    card = state.card_instances[0]

    assert state.player(player.player_id) is player
    assert state.card(card.instance_id) is card


def test_state_lookup_raises_for_unknown_ids() -> None:
    state = build_sample_game_state()

    with pytest.raises(UnknownPlayerError):
        _ = state.player(PlayerId("missing"))

    with pytest.raises(UnknownCardInstanceError):
        _ = state.card(CardInstanceId("missing"))


def test_state_cached_or_compute_reuses_computed_value() -> None:
    state = build_sample_game_state()
    calls = 0

    def build_value() -> tuple[str, int]:
        nonlocal calls
        calls += 1
        return ("cached", calls)

    first = state.cached_or_compute("example", build_value)
    second = state.cached_or_compute("example", build_value)

    assert first == ("cached", 1)
    assert second is first
    assert calls == 1


def test_wrong_player_cannot_act_during_round() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PLAYER_ONE_ID)
    player_one_card = state.player(PLAYER_ONE_ID).hand[0]
    card_name = card_registry.get(state.card(player_one_card).definition_id).name
    with pytest.raises(
        IllegalActionError,
        match=f"Only the current player may act.*Attempted play: {card_name!r}",
    ):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PLAYER_TWO_ID,
                card_instance_id=player_one_card,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
        )


def test_in_round_actions_are_rejected_outside_in_round_phase() -> None:
    not_started_state = build_sample_game_state()

    with pytest.raises(IllegalActionError, match="IN_ROUND phase"):
        _ = apply_action(
            not_started_state,
            PassAction(player_id=PLAYER_ONE_ID),
        )

    started_state, card_registry = build_started_game_state(starting_player=PLAYER_ONE_ID)
    card_to_play = started_state.player(PLAYER_ONE_ID).hand[0]
    with pytest.raises(IllegalActionError, match="IN_ROUND phase"):
        _ = apply_action(
            started_state,
            PlayCardAction(
                player_id=PLAYER_ONE_ID,
                card_instance_id=card_to_play,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
        )
