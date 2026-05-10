from collections import Counter

from gwent_engine.cards import CardRegistry
from gwent_engine.core.enums import (
    ACTIVE_TURN_PHASES,
    AbilityKind,
    CardType,
    GameStatus,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.errors import InvariantError
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import CardInstance, GameState, PlayerState


def check_game_state_invariants(
    state: GameState,
    *,
    card_registry: CardRegistry | None = None,
) -> None:
    """Validate reducer-facing runtime invariants for a complete ``GameState``.

    This is the engine's central post-transition safety check. Tests call it
    after setup helpers and reducer application to ensure that zone ownership,
    phase/status consistency, and match-end bookkeeping still describe a
    coherent runtime state. Production callers may also use it when loading or
    replaying serialized matches.
    """
    _check_card_locations(state, card_registry=card_registry)
    _check_phase_status_consistency(state)
    _check_current_player(state)
    _check_gem_bounds(state)
    _check_pending_choice(state)
    _check_match_end_consistency(state)
    _check_leader_state(state)
    _check_pending_avenger_summons(state)


def _check_card_locations(
    state: GameState,
    *,
    card_registry: CardRegistry | None,
) -> None:
    located_cards = list(_iter_located_cards(state))
    _check_card_container_membership(state, located_cards)

    for owner, zone, row, card_id, location_kind in located_cards:
        card = state.card(card_id)
        _check_card_location_identity(card_id, card.zone, zone, card.row, row)
        if zone == Zone.BATTLEFIELD:
            _check_battlefield_card_location(
                state,
                owner=owner,
                card_id=card_id,
                location_kind=location_kind,
                card_registry=card_registry,
            )
            continue
        if zone == Zone.WEATHER:
            _check_weather_card_location(state, card_id=card_id)
            continue
        _check_non_battlefield_card_location(state, owner=owner, card_id=card_id)


def _check_current_player(state: GameState) -> None:
    requires_current_player = state.phase in ACTIVE_TURN_PHASES
    if requires_current_player and state.current_player is None:
        raise InvariantError(f"Phase {state.phase!r} requires a current player.")
    if not requires_current_player and state.current_player is not None:
        raise InvariantError(f"Phase {state.phase!r} cannot have a current player.")

    if state.phase == Phase.IN_ROUND and state.current_player is not None:
        current_player = state.player(state.current_player)
        if current_player.has_passed:
            raise InvariantError("The current player cannot already be marked as passed.")


def _check_phase_status_consistency(state: GameState) -> None:
    expected_status_by_phase = {
        Phase.NOT_STARTED: GameStatus.NOT_STARTED,
        Phase.MULLIGAN: GameStatus.IN_PROGRESS,
        Phase.IN_ROUND: GameStatus.IN_PROGRESS,
        Phase.ROUND_RESOLUTION: GameStatus.IN_PROGRESS,
        Phase.MATCH_ENDED: GameStatus.MATCH_ENDED,
    }
    expected_status = expected_status_by_phase[state.phase]
    if state.status != expected_status:
        raise InvariantError(
            f"Phase {state.phase!r} requires status {expected_status!r}, found {state.status!r}."
        )


def _check_gem_bounds(state: GameState) -> None:
    for player in state.players:
        if player.gems_remaining < 0 or player.gems_remaining > 2:
            raise InvariantError(
                f"Player {player.player_id!r} gems_remaining is out of bounds: "
                + f"{player.gems_remaining}"
            )


def _check_pending_choice(state: GameState) -> None:
    pending_choice = state.pending_choice
    if pending_choice is None:
        return
    if state.phase != Phase.IN_ROUND or state.status != GameStatus.IN_PROGRESS:
        raise InvariantError("Pending choices are only valid during active in-round play.")
    if state.current_player != pending_choice.player_id:
        raise InvariantError("Pending choice player must remain the current player.")
    if not pending_choice.legal_target_card_instance_ids and not pending_choice.legal_rows:
        raise InvariantError("Pending choices must expose at least one legal selection.")
    if pending_choice.source_card_instance_id is not None:
        source_card = state.card(pending_choice.source_card_instance_id)
        if source_card.owner != pending_choice.player_id:
            raise InvariantError("Pending-choice source cards must belong to the choosing player.")
        if source_card.zone != Zone.HAND:
            raise InvariantError("Pending-choice source cards must remain in hand until resolved.")
    if pending_choice.source_leader_id is not None:
        player = state.player(pending_choice.player_id)
        if player.leader.leader_id != pending_choice.source_leader_id:
            raise InvariantError("Pending-choice leader source must match the choosing player.")
        if player.leader.used:
            raise InvariantError(
                "Pending-choice leader sources must remain unused until resolution."
            )


def _check_match_end_consistency(state: GameState) -> None:
    if not _state_is_ended(state):
        _check_active_match_has_no_winner(state)
        return

    _check_ended_match_phase_and_status(state)
    _check_ended_match_has_no_current_player(state)
    _check_ended_match_has_eliminated_player(state)
    _check_ended_match_winner(state)


def _check_card_container_membership(
    state: GameState,
    located_cards: list[tuple[PlayerId | None, Zone, Row | None, CardInstanceId, str]],
) -> None:
    card_ids = {card.instance_id for card in state.card_instances}
    counts = Counter(card_id for _, _, _, card_id, _ in located_cards)

    duplicate_ids = sorted(card_id for card_id, count in counts.items() if count > 1)
    if duplicate_ids:
        raise InvariantError(f"Card instances appear in multiple containers: {duplicate_ids!r}")

    located_card_ids = set(counts)
    missing_ids = sorted(card_ids - located_card_ids)
    if missing_ids:
        raise InvariantError(f"Card instances are missing from containers: {missing_ids!r}")

    unknown_ids = sorted(located_card_ids - card_ids)
    if unknown_ids:
        raise InvariantError(f"Containers reference unknown card instances: {unknown_ids!r}")


def _check_card_location_identity(
    card_id: CardInstanceId,
    actual_zone: Zone,
    stored_zone: Zone,
    actual_row: Row | None,
    stored_row: Row | None,
) -> None:
    if actual_zone != stored_zone:
        raise InvariantError(
            f"Card {card_id!r} is in zone {actual_zone!r} but stored under {stored_zone!r}."
        )
    if actual_row != stored_row:
        raise InvariantError(
            f"Card {card_id!r} row is {actual_row!r} but stored under {stored_row!r}."
        )


def _check_non_battlefield_card_location(
    state: GameState,
    *,
    owner: PlayerId | None,
    card_id: CardInstanceId,
) -> None:
    assert owner is not None
    card = state.card(card_id)
    if card.owner != owner:
        raise InvariantError(
            f"Card {card_id!r} belongs to {card.owner!r} but is stored under {owner!r}."
        )
    if card.battlefield_side is not None:
        raise InvariantError(f"Non-battlefield card {card_id!r} cannot declare battlefield_side.")


def _check_battlefield_card_location(
    state: GameState,
    *,
    owner: PlayerId | None,
    card_id: CardInstanceId,
    location_kind: str,
    card_registry: CardRegistry | None,
) -> None:
    card = state.card(card_id)
    if location_kind == "battlefield_weather":
        _check_battlefield_weather_card_has_no_side(card, card_id=card_id)
        return

    assert owner is not None
    if card.battlefield_side != owner:
        raise InvariantError(
            f"Battlefield card {card_id!r} is stored under {owner!r} but has "
            + f"battlefield_side {card.battlefield_side!r}."
        )
    if card.owner == owner:
        return
    if card_registry is not None and _card_can_be_on_opponent_battlefield_side(
        state, card_registry, card_id
    ):
        return
    raise InvariantError(
        f"Card {card_id!r} belongs to {card.owner!r} but is stored under {owner!r}."
    )


def _check_battlefield_weather_card_has_no_side(
    card: CardInstance,
    *,
    card_id: CardInstanceId,
) -> None:
    if card.battlefield_side is not None:
        raise InvariantError(f"Weather card {card_id!r} cannot declare battlefield_side.")


def _check_weather_card_location(
    state: GameState,
    *,
    card_id: CardInstanceId,
) -> None:
    card = state.card(card_id)
    if card.battlefield_side is not None:
        raise InvariantError(f"Weather card {card_id!r} cannot declare battlefield_side.")


def _state_is_ended(state: GameState) -> bool:
    return state.status == GameStatus.MATCH_ENDED or state.phase == Phase.MATCH_ENDED


def _check_active_match_has_no_winner(state: GameState) -> None:
    if state.match_winner is not None:
        raise InvariantError("Active matches cannot declare match_winner.")


def _check_ended_match_phase_and_status(state: GameState) -> None:
    if state.status != GameStatus.MATCH_ENDED or state.phase != Phase.MATCH_ENDED:
        raise InvariantError("Ended matches must set both status and phase to MATCH_ENDED.")


def _check_ended_match_has_no_current_player(state: GameState) -> None:
    if state.current_player is not None:
        raise InvariantError("Ended matches cannot have a current player.")


def _check_ended_match_has_eliminated_player(state: GameState) -> None:
    if any(player.gems_remaining == 0 for player in state.players):
        return
    raise InvariantError("Ended matches require at least one player to have zero gems.")


def _check_ended_match_winner(state: GameState) -> None:
    eliminated_players = tuple(player for player in state.players if player.gems_remaining == 0)
    if _is_double_elimination(state, eliminated_players):
        _check_double_elimination_has_no_winner(state)
        return

    surviving_player = next(
        player.player_id for player in state.players if player.gems_remaining > 0
    )
    if state.match_winner != surviving_player:
        raise InvariantError("Ended matches with one surviving player must declare that winner.")


def _is_double_elimination(
    state: GameState,
    eliminated_players: tuple[PlayerState, ...],
) -> bool:
    return len(eliminated_players) == len(state.players)


def _check_double_elimination_has_no_winner(state: GameState) -> None:
    if state.match_winner is not None:
        raise InvariantError("Double-elimination draws must not declare a match_winner.")


def _check_leader_state(state: GameState) -> None:
    if state.phase == Phase.NOT_STARTED:
        for player in state.players:
            if player.leader.used:
                raise InvariantError("NOT_STARTED games cannot have already-used leaders.")
            if player.leader.horn_row is not None:
                raise InvariantError("NOT_STARTED games cannot have active leader horn rows.")
    for player in state.players:
        if player.leader.horn_row is not None and not player.leader.used:
            raise InvariantError("Leader horn rows require the leader ability to be marked used.")


def _check_pending_avenger_summons(state: GameState) -> None:
    pending_sources = [summon.source_card_instance_id for summon in state.pending_avenger_summons]
    if len(set(pending_sources)) != len(pending_sources):
        raise InvariantError("Pending Avenger summons must have unique source card ids.")
    for summon in state.pending_avenger_summons:
        source_card = state.card(summon.source_card_instance_id)
        if source_card.zone == Zone.BATTLEFIELD:
            raise InvariantError(
                "Queued Avenger summons cannot keep the source on the battlefield."
            )


def _iter_located_cards(
    state: GameState,
) -> tuple[tuple[PlayerId | None, Zone, Row | None, CardInstanceId, str], ...]:
    locations: list[tuple[PlayerId | None, Zone, Row | None, CardInstanceId, str]] = []
    for player in state.players:
        locations.extend(_player_zone_entries(player))
    for row in (Row.CLOSE, Row.RANGED, Row.SIEGE):
        locations.extend(
            (None, Zone.WEATHER, row, card_id, "battlefield_weather")
            for card_id in state.battlefield_weather.cards_for(row)
        )
    return tuple(locations)


def _player_zone_entries(
    player: PlayerState,
) -> tuple[tuple[PlayerId | None, Zone, Row | None, CardInstanceId, str], ...]:
    entries: list[tuple[PlayerId | None, Zone, Row | None, CardInstanceId, str]] = []
    entries.extend(
        (player.player_id, Zone.DECK, None, card_id, "player_zone") for card_id in player.deck
    )
    entries.extend(
        (player.player_id, Zone.HAND, None, card_id, "player_zone") for card_id in player.hand
    )
    entries.extend(
        (player.player_id, Zone.DISCARD, None, card_id, "player_zone") for card_id in player.discard
    )
    for row in (Row.CLOSE, Row.RANGED, Row.SIEGE):
        entries.extend(
            (player.player_id, Zone.BATTLEFIELD, row, card_id, "player_row")
            for card_id in player.rows.cards_for(row)
        )
    return tuple(entries)


def _card_can_be_on_opponent_battlefield_side(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    return definition.card_type == CardType.UNIT and AbilityKind.SPY in definition.ability_kinds
