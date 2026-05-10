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
from gwent_engine.core.errors import InvariantError
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    PlayerId,
)
from gwent_engine.core.invariants import check_game_state_invariants
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    LeaderState,
    PendingChoice,
    PlayerState,
    RowState,
)

from tests.engine.support import CARD_REGISTRY


def test_basic_runtime_invariants_pass_for_valid_state() -> None:
    state = _build_valid_state()

    check_game_state_invariants(state)


def test_invariants_fail_when_card_zone_disagrees_with_container() -> None:
    state = _build_valid_state(
        card_instances=(
            CardInstance(
                instance_id=CardInstanceId("card_1"),
                definition_id=CardDefinitionId("monsters_griffin"),
                owner=PlayerId("p1"),
                zone=Zone.HAND,
            ),
        )
    )

    with pytest.raises(InvariantError, match="zone"):
        check_game_state_invariants(state)


def test_invariants_fail_when_current_player_has_already_passed() -> None:
    player_one = PlayerState(
        player_id=PlayerId("p1"),
        faction=FactionId.MONSTERS,
        leader=LeaderState(leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders")),
        deck=(CardInstanceId("card_1"),),
        hand=(),
        discard=(),
        rows=RowState(),
        has_passed=True,
    )
    player_two = PlayerState(
        player_id=PlayerId("p2"),
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
                owner=PlayerId("p1"),
                zone=Zone.DECK,
            ),
        ),
        current_player=PlayerId("p1"),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
    )

    with pytest.raises(InvariantError, match="current player"):
        check_game_state_invariants(state)


def test_spy_card_may_live_on_the_opponent_battlefield_side() -> None:
    state = GameState(
        game_id=GameId("game_1"),
        players=(
            PlayerState(
                player_id=PlayerId("p1"),
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(),
                rows=RowState(),
            ),
            PlayerState(
                player_id=PlayerId("p2"),
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
                owner=PlayerId("p1"),
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
                battlefield_side=PlayerId("p2"),
            ),
        ),
        current_player=PlayerId("p1"),
        starting_player=PlayerId("p1"),
        round_starter=PlayerId("p1"),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
    )

    check_game_state_invariants(state, card_registry=CARD_REGISTRY)


def test_non_spy_card_cannot_live_on_the_opponent_battlefield_side() -> None:
    state = GameState(
        game_id=GameId("game_1"),
        players=(
            PlayerState(
                player_id=PlayerId("p1"),
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(),
                rows=RowState(),
            ),
            PlayerState(
                player_id=PlayerId("p2"),
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
                owner=PlayerId("p1"),
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
                battlefield_side=PlayerId("p2"),
            ),
        ),
        current_player=PlayerId("p1"),
        starting_player=PlayerId("p1"),
        round_starter=PlayerId("p1"),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
    )

    with pytest.raises(InvariantError, match="belongs to"):
        check_game_state_invariants(state, card_registry=CARD_REGISTRY)


def test_ended_match_may_skip_completed_mulligans_when_player_left_early() -> None:
    player_one = PlayerState(
        player_id=PlayerId("p1"),
        faction=FactionId.MONSTERS,
        leader=LeaderState(leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders")),
        deck=(CardInstanceId("card_1"),),
        hand=(),
        discard=(),
        rows=RowState(),
        gems_remaining=0,
    )
    player_two = PlayerState(
        player_id=PlayerId("p2"),
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
                owner=PlayerId("p1"),
                zone=Zone.DECK,
            ),
        ),
        phase=Phase.MATCH_ENDED,
        status=GameStatus.MATCH_ENDED,
        match_winner=PlayerId("p2"),
    )

    check_game_state_invariants(state)


def test_pending_choice_source_card_must_remain_in_hand_until_resolution() -> None:
    state = GameState(
        game_id=GameId("game_1"),
        players=(
            PlayerState(
                player_id=PlayerId("p1"),
                faction=FactionId.SCOIATAEL,
                leader=LeaderState(leader_id=LeaderId("scoiatael_francesca_the_beautiful")),
                deck=(),
                hand=(),
                discard=(CardInstanceId("p1_decoy_trick_card"),),
                rows=RowState(close=(CardInstanceId("p1_vanguard_frontliner"),)),
            ),
            PlayerState(
                player_id=PlayerId("p2"),
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
                owner=PlayerId("p1"),
                zone=Zone.DISCARD,
            ),
            CardInstance(
                instance_id=CardInstanceId("p1_vanguard_frontliner"),
                definition_id=CardDefinitionId("scoiatael_vanguard"),
                owner=PlayerId("p1"),
                zone=Zone.BATTLEFIELD,
                row=Row.CLOSE,
                battlefield_side=PlayerId("p1"),
            ),
        ),
        pending_choice=PendingChoice(
            choice_id=ChoiceId("decoy_choice"),
            player_id=PlayerId("p1"),
            kind=ChoiceKind.SELECT_CARD_INSTANCE,
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id=CardInstanceId("p1_decoy_trick_card"),
            legal_target_card_instance_ids=(CardInstanceId("p1_vanguard_frontliner"),),
        ),
        current_player=PlayerId("p1"),
        starting_player=PlayerId("p1"),
        round_starter=PlayerId("p1"),
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
        player_id=PlayerId("p1"),
        faction=FactionId.MONSTERS,
        leader=LeaderState(leader_id=LeaderId("monsters_eredin_commander_of_the_red_riders")),
        deck=(CardInstanceId("card_1"),),
        hand=(),
        discard=(),
        rows=RowState(),
    )
    player_two = PlayerState(
        player_id=PlayerId("p2"),
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
                owner=PlayerId("p1"),
                zone=Zone.DECK,
            ),
        ),
        phase=Phase.NOT_STARTED,
        status=GameStatus.NOT_STARTED,
    )
