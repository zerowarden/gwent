from __future__ import annotations

from collections.abc import Mapping
from functools import partial

from gwent_shared.extract import (
    expect_mapping,
    optional_constructor_field,
    require_bool_field,
    require_constructor_field,
    require_int_field,
    require_sequence_field,
    require_str_field,
)

from gwent_engine.ai.observations import (
    ObservedCard,
    ObservedDeckEntry,
    ObservedLeader,
    ObservedRows,
    PlayerObservation,
    PublicGameStateView,
    PublicPendingChoiceView,
    PublicPlayerStateView,
    VisiblePendingChoiceView,
)
from gwent_engine.core import ChoiceKind, ChoiceSourceKind, FactionId, GameStatus, Phase, Row
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    player_id,
)

_mapping = partial(expect_mapping, context="observation", error_factory=ValueError)
_sequence = partial(require_sequence_field, context="observation", error_factory=ValueError)
_text = partial(require_str_field, context="observation", error_factory=ValueError)
_integer = partial(require_int_field, context="observation", error_factory=ValueError)
_boolean = partial(require_bool_field, context="observation", error_factory=ValueError)
_construct = partial(require_constructor_field, context="observation", error_factory=ValueError)
_optional = partial(optional_constructor_field, context="observation", error_factory=ValueError)


def player_observation_from_dict(payload: object) -> PlayerObservation:
    data = _mapping(payload)
    public = _mapping(data.get("public_state"))
    players = tuple(_player(item) for item in _sequence(public, "players"))
    if len(players) != 2 or players[0].player_id == players[1].player_id:
        raise ValueError("Observation requires two distinct players.")
    deck = tuple(_deck_entry(item) for item in _sequence(data, "viewer_deck_composition"))
    handles = [handle for entry in deck for handle in entry.instance_ids]
    if len(set(handles)) != len(handles):
        raise ValueError("Observation contains duplicate deck handles.")
    pending = public.get("pending_choice")
    pending_data = None if pending is None else _mapping(pending)
    return PlayerObservation(
        viewer_player_id=_construct(data, "viewer_player_id", player_id),
        public_state=PublicGameStateView(
            game_id=GameId(_text(public, "game_id")),
            phase=_construct(public, "phase", Phase),
            status=_construct(public, "status", GameStatus),
            current_player=_optional(public, "current_player", player_id),
            starting_player=_optional(public, "starting_player", player_id),
            round_starter=_optional(public, "round_starter", player_id),
            round_number=_integer(public, "round_number"),
            match_winner=_optional(public, "match_winner", player_id),
            players=(players[0], players[1]),
            battlefield_weather=_rows(public.get("battlefield_weather")),
            pending_choice=None
            if pending_data is None
            else PublicPendingChoiceView(
                player_id=_construct(pending_data, "player_id", player_id),
                kind=_construct(pending_data, "kind", ChoiceKind),
                source_kind=_construct(pending_data, "source_kind", ChoiceSourceKind),
            ),
        ),
        viewer_hand=_cards(data, "viewer_hand"),
        viewer_deck_composition=tuple(sorted(deck, key=lambda entry: entry.definition_id)),
        visible_pending_choice=_visible_choice(data.get("visible_pending_choice")),
    )


def _deck_entry(payload: object) -> ObservedDeckEntry:
    data = _mapping(payload)
    handles = _sequence(data, "instance_ids")
    if not all(isinstance(handle, str) and handle for handle in handles):
        raise ValueError("Deck handles must be nonempty strings.")
    entry = ObservedDeckEntry(
        definition_id=CardDefinitionId(_text(data, "definition_id")),
        instance_ids=tuple(sorted(CardInstanceId(str(handle)) for handle in handles)),
    )
    if entry.count != _integer(data, "count"):
        raise ValueError("Deck count does not match its handles.")
    return entry


def _cards(data: Mapping[str, object], key: str) -> tuple[ObservedCard, ...]:
    return tuple(_card(item) for item in _sequence(data, key))


def _card(payload: object) -> ObservedCard:
    data = _mapping(payload)
    return ObservedCard(
        instance_id=CardInstanceId(_text(data, "instance_id")),
        definition_id=CardDefinitionId(_text(data, "definition_id")),
        owner=_construct(data, "owner", player_id),
        row=_optional(data, "row", Row),
        battlefield_side=_optional(data, "battlefield_side", player_id),
    )


def _rows(payload: object) -> ObservedRows:
    data = _mapping(payload)
    return ObservedRows(
        close=_cards(data, "close"), ranged=_cards(data, "ranged"), siege=_cards(data, "siege")
    )


def _player(payload: object) -> PublicPlayerStateView:
    data = _mapping(payload)
    leader = _mapping(data.get("leader"))
    return PublicPlayerStateView(
        player_id=_construct(data, "player_id", player_id),
        faction=_construct(data, "faction", FactionId),
        leader=ObservedLeader(
            leader_id=LeaderId(_text(leader, "leader_id")),
            used=_boolean(leader, "used"),
            disabled=_boolean(leader, "disabled"),
            horn_row=_optional(leader, "horn_row", Row),
            available_horn_row=_optional(leader, "available_horn_row", Row),
        ),
        deck_count=_integer(data, "deck_count"),
        hand_count=_integer(data, "hand_count"),
        discard=_cards(data, "discard"),
        rows=_rows(data.get("rows")),
        gems_remaining=_integer(data, "gems_remaining"),
        round_wins=_integer(data, "round_wins"),
        has_passed=_boolean(data, "has_passed"),
    )


def _visible_choice(payload: object) -> VisiblePendingChoiceView | None:
    if payload is None:
        return None
    data = _mapping(payload)
    targets = _sequence(data, "legal_target_card_instance_ids")
    rows = _sequence(data, "legal_rows")
    if not all(isinstance(target, str) and target for target in targets):
        raise ValueError("Choice targets must be nonempty strings.")
    return VisiblePendingChoiceView(
        choice_id=ChoiceId(_text(data, "choice_id")),
        player_id=_construct(data, "player_id", player_id),
        kind=_construct(data, "kind", ChoiceKind),
        source_kind=_construct(data, "source_kind", ChoiceSourceKind),
        source_card_instance_id=_optional(data, "source_card_instance_id", CardInstanceId),
        source_leader_id=_optional(data, "source_leader_id", LeaderId),
        legal_target_card_instance_ids=tuple(CardInstanceId(str(target)) for target in targets),
        legal_rows=tuple(Row(str(row)) for row in rows),
        min_selections=_integer(data, "min_selections"),
        max_selections=_integer(data, "max_selections"),
        source_row=_optional(data, "source_row", Row),
    )
