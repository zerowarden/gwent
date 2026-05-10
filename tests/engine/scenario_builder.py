from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Self

from gwent_engine.core import (
    ChoiceKind,
    ChoiceSourceKind,
    FactionId,
    GameStatus,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.ids import CardInstanceId, ChoiceId, GameId, LeaderId, PlayerId
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    LeaderState,
    PendingChoice,
    PlayerState,
    RowState,
)

from .primitives import PLAYER_ONE_ID, PLAYER_TWO_ID, make_card_instance

DEFAULT_SCENARIO_FACTION = FactionId("scoiatael")
DEFAULT_SCENARIO_LEADER = LeaderId("scoiatael_francesca_the_beautiful")


DEFAULT_LEADER_BY_FACTION = {
    FactionId("monsters"): LeaderId("monsters_eredin_commander_of_the_red_riders"),
    FactionId("nilfgaard"): LeaderId("nilfgaard_emhyr_the_white_flame"),
    FactionId("northern_realms"): LeaderId("northern_realms_foltest_the_siegemaster"),
    FactionId("scoiatael"): LeaderId("scoiatael_francesca_the_beautiful"),
    FactionId("skellige"): LeaderId("skellige_king_bran"),
}


def scenario(name: str) -> ScenarioBuilder:
    return ScenarioBuilder(name)


def card(
    instance_id: str | CardInstanceId,
    definition_id: str,
    *,
    owner: str | PlayerId | None = None,
) -> ScenarioCard:
    return ScenarioCard(
        instance_id=str(instance_id),
        definition_id=definition_id,
        owner=None if owner is None else _player_id(owner),
    )


def rows(
    *,
    close: tuple[ScenarioCard, ...] | list[ScenarioCard] = (),
    ranged: tuple[ScenarioCard, ...] | list[ScenarioCard] = (),
    siege: tuple[ScenarioCard, ...] | list[ScenarioCard] = (),
) -> ScenarioRows:
    return ScenarioRows(
        close=tuple(close),
        ranged=tuple(ranged),
        siege=tuple(siege),
    )


@dataclass(frozen=True, slots=True)
class ScenarioCard:
    instance_id: str
    definition_id: str
    owner: PlayerId | None


@dataclass(frozen=True, slots=True)
class ScenarioRows:
    close: tuple[ScenarioCard, ...] = ()
    ranged: tuple[ScenarioCard, ...] = ()
    siege: tuple[ScenarioCard, ...] = ()

    def ids(self) -> RowState:
        return RowState(
            close=tuple(CardInstanceId(card.instance_id) for card in self.close),
            ranged=tuple(CardInstanceId(card.instance_id) for card in self.ranged),
            siege=tuple(CardInstanceId(card.instance_id) for card in self.siege),
        )


@dataclass(frozen=True, slots=True)
class ScenarioPlayer:
    player_id: PlayerId
    faction: FactionId = DEFAULT_SCENARIO_FACTION
    leader_id: LeaderId = DEFAULT_SCENARIO_LEADER
    leader_used: bool = False
    leader_disabled: bool = False
    leader_horn_row: Row | None = None
    gems_remaining: int = 2
    round_wins: int = 0
    passed: bool = False
    hand: tuple[ScenarioCard, ...] = ()
    deck: tuple[ScenarioCard, ...] = ()
    discard: tuple[ScenarioCard, ...] = ()
    board: ScenarioRows = ScenarioRows()

    @classmethod
    def default(cls, player_id: PlayerId) -> ScenarioPlayer:
        return cls(player_id=player_id)

    def with_updates(
        self,
        *,
        faction: str | FactionId | None = None,
        leader_id: str | LeaderId | None = None,
        leader_used: bool | None = None,
        leader_disabled: bool | None = None,
        leader_horn_row: Row | None = None,
        gems_remaining: int | None = None,
        round_wins: int | None = None,
        passed: bool | None = None,
        hand: tuple[ScenarioCard, ...] | list[ScenarioCard] | None = None,
        deck: tuple[ScenarioCard, ...] | list[ScenarioCard] | None = None,
        discard: tuple[ScenarioCard, ...] | list[ScenarioCard] | None = None,
        board: ScenarioRows | None = None,
    ) -> ScenarioPlayer:
        resolved_faction = self.faction if faction is None else _faction_id(faction)
        resolved_leader = self.leader_id if leader_id is None else _leader_id(leader_id)
        if (
            leader_id is None
            and faction is not None
            and self.leader_id == DEFAULT_LEADER_BY_FACTION[self.faction]
        ):
            resolved_leader = DEFAULT_LEADER_BY_FACTION.get(resolved_faction, self.leader_id)
        return replace(
            self,
            faction=resolved_faction,
            leader_id=resolved_leader,
            leader_used=self.leader_used if leader_used is None else leader_used,
            leader_disabled=self.leader_disabled if leader_disabled is None else leader_disabled,
            leader_horn_row=self.leader_horn_row if leader_horn_row is None else leader_horn_row,
            gems_remaining=self.gems_remaining if gems_remaining is None else gems_remaining,
            round_wins=self.round_wins if round_wins is None else round_wins,
            passed=self.passed if passed is None else passed,
            hand=self.hand if hand is None else tuple(hand),
            deck=self.deck if deck is None else tuple(deck),
            discard=self.discard if discard is None else tuple(discard),
            board=self.board if board is None else board,
        )


@dataclass(frozen=True, slots=True)
class PendingChoiceSpec:
    choice_id: str
    player_id: PlayerId
    source_kind: ChoiceSourceKind
    source_card_instance_id: str | None = None
    source_leader_id: LeaderId | None = None
    legal_target_card_instance_ids: tuple[str, ...] = ()
    legal_rows: tuple[Row, ...] = ()
    kind: ChoiceKind = ChoiceKind.SELECT_CARD_INSTANCE
    min_selections: int = 1
    max_selections: int = 1
    source_row: Row | None = None

    def build(self) -> PendingChoice:
        return PendingChoice(
            choice_id=ChoiceId(self.choice_id),
            player_id=self.player_id,
            kind=self.kind,
            source_kind=self.source_kind,
            source_card_instance_id=(
                None
                if self.source_card_instance_id is None
                else CardInstanceId(self.source_card_instance_id)
            ),
            source_leader_id=self.source_leader_id,
            legal_target_card_instance_ids=tuple(
                CardInstanceId(instance_id) for instance_id in self.legal_target_card_instance_ids
            ),
            legal_rows=self.legal_rows,
            min_selections=self.min_selections,
            max_selections=self.max_selections,
            source_row=self.source_row,
        )


class ScenarioBuilder:
    def __init__(self, name: str) -> None:
        self._name: str = name
        self._players: dict[PlayerId, ScenarioPlayer] = {
            PLAYER_ONE_ID: ScenarioPlayer.default(PLAYER_ONE_ID),
            PLAYER_TWO_ID: ScenarioPlayer.default(PLAYER_TWO_ID),
        }
        self._round_number: int = 1
        self._phase: Phase = Phase.IN_ROUND
        self._status: GameStatus = GameStatus.IN_PROGRESS
        self._current_player: PlayerId | None = PLAYER_ONE_ID
        self._starting_player: PlayerId = PLAYER_ONE_ID
        self._round_starter: PlayerId = PLAYER_ONE_ID
        self._weather: ScenarioRows = ScenarioRows()
        self._pending_choice: PendingChoiceSpec | None = None

    def round(self, number: int) -> Self:
        self._round_number = number
        return self

    def phase(self, phase: Phase) -> Self:
        self._phase = phase
        return self

    def status(self, status: GameStatus) -> Self:
        self._status = status
        return self

    def current_player(self, player_id: str | PlayerId | None) -> Self:
        self._current_player = None if player_id is None else _player_id(player_id)
        return self

    def turn_order(
        self,
        *,
        starting_player: str | PlayerId | None = None,
        round_starter: str | PlayerId | None = None,
    ) -> Self:
        if starting_player is not None:
            self._starting_player = _player_id(starting_player)
        if round_starter is not None:
            self._round_starter = _player_id(round_starter)
        return self

    def player(
        self,
        player_id: str | PlayerId,
        *,
        faction: str | FactionId | None = None,
        leader_id: str | LeaderId | None = None,
        leader_used: bool | None = None,
        leader_disabled: bool | None = None,
        leader_horn_row: Row | None = None,
        gems_remaining: int | None = None,
        round_wins: int | None = None,
        passed: bool | None = None,
        hand: tuple[ScenarioCard, ...] | list[ScenarioCard] | None = None,
        deck: tuple[ScenarioCard, ...] | list[ScenarioCard] | None = None,
        discard: tuple[ScenarioCard, ...] | list[ScenarioCard] | None = None,
        board: ScenarioRows | None = None,
    ) -> Self:
        resolved_player_id = _player_id(player_id)
        self._players[resolved_player_id] = self._players[resolved_player_id].with_updates(
            faction=faction,
            leader_id=leader_id,
            leader_used=leader_used,
            leader_disabled=leader_disabled,
            leader_horn_row=leader_horn_row,
            gems_remaining=gems_remaining,
            round_wins=round_wins,
            passed=passed,
            hand=hand,
            deck=deck,
            discard=discard,
            board=board,
        )
        return self

    def weather(self, weather_rows: ScenarioRows) -> Self:
        self._weather = weather_rows
        return self

    def pending_choice(
        self,
        *,
        choice_id: str,
        player_id: str | PlayerId,
        source_kind: ChoiceSourceKind,
        source_card_instance_id: str | None = None,
        source_leader_id: str | LeaderId | None = None,
        legal_target_card_instance_ids: tuple[str, ...] | list[str],
        legal_rows: tuple[Row, ...] | list[Row] = (),
        kind: ChoiceKind = ChoiceKind.SELECT_CARD_INSTANCE,
        min_selections: int = 1,
        max_selections: int = 1,
        source_row: Row | None = None,
    ) -> Self:
        self._pending_choice = PendingChoiceSpec(
            choice_id=choice_id,
            player_id=_player_id(player_id),
            source_kind=source_kind,
            source_card_instance_id=source_card_instance_id,
            source_leader_id=None if source_leader_id is None else _leader_id(source_leader_id),
            legal_target_card_instance_ids=tuple(legal_target_card_instance_ids),
            legal_rows=tuple(legal_rows),
            kind=kind,
            min_selections=min_selections,
            max_selections=max_selections,
            source_row=source_row,
        )
        return self

    def card_choice(
        self,
        *,
        choice_id: str,
        player_id: str | PlayerId,
        source_kind: ChoiceSourceKind,
        source_card_instance_id: str,
        legal_target_card_instance_ids: tuple[str, ...] | list[str],
    ) -> Self:
        return self.pending_choice(
            choice_id=choice_id,
            player_id=player_id,
            source_kind=source_kind,
            source_card_instance_id=source_card_instance_id,
            legal_target_card_instance_ids=legal_target_card_instance_ids,
        )

    def leader_choice(
        self,
        *,
        choice_id: str,
        player_id: str | PlayerId,
        source_leader_id: str | LeaderId,
        legal_target_card_instance_ids: tuple[str, ...] | list[str] = (),
        legal_rows: tuple[Row, ...] | list[Row] = (),
        min_selections: int = 1,
        max_selections: int = 1,
        source_row: Row | None = None,
        kind: ChoiceKind = ChoiceKind.SELECT_CARD_INSTANCE,
    ) -> Self:
        return self.pending_choice(
            choice_id=choice_id,
            player_id=player_id,
            source_kind=ChoiceSourceKind.LEADER_ABILITY,
            source_leader_id=source_leader_id,
            legal_target_card_instance_ids=legal_target_card_instance_ids,
            legal_rows=legal_rows,
            min_selections=min_selections,
            max_selections=max_selections,
            source_row=source_row,
            kind=kind,
        )

    def build(self) -> GameState:
        return GameState(
            game_id=GameId(self._name),
            players=(
                self._build_player_state(self._players[PLAYER_ONE_ID]),
                self._build_player_state(self._players[PLAYER_TWO_ID]),
            ),
            card_instances=self._build_card_instances(),
            weather=self._weather.ids(),
            pending_choice=None if self._pending_choice is None else self._pending_choice.build(),
            current_player=self._current_player,
            starting_player=self._starting_player,
            round_starter=self._round_starter,
            round_number=self._round_number,
            phase=self._phase,
            status=self._status,
        )

    def _build_player_state(self, spec: ScenarioPlayer) -> PlayerState:
        return PlayerState(
            player_id=spec.player_id,
            faction=spec.faction,
            leader=LeaderState(
                leader_id=spec.leader_id,
                used=spec.leader_used,
                disabled=spec.leader_disabled,
                horn_row=spec.leader_horn_row,
            ),
            deck=tuple(CardInstanceId(card.instance_id) for card in spec.deck),
            hand=tuple(CardInstanceId(card.instance_id) for card in spec.hand),
            discard=tuple(CardInstanceId(card.instance_id) for card in spec.discard),
            rows=spec.board.ids(),
            gems_remaining=spec.gems_remaining,
            round_wins=spec.round_wins,
            has_passed=spec.passed,
        )

    def _build_card_instances(self) -> tuple[CardInstance, ...]:
        built_instances: list[CardInstance] = []
        seen_ids: set[str] = set()
        for spec in self._players.values():
            built_instances.extend(
                self._build_zone_cards(
                    spec.hand,
                    zone=Zone.HAND,
                    seen_ids=seen_ids,
                    default_owner=spec.player_id,
                )
            )
            built_instances.extend(
                self._build_zone_cards(
                    spec.deck,
                    zone=Zone.DECK,
                    seen_ids=seen_ids,
                    default_owner=spec.player_id,
                )
            )
            built_instances.extend(
                self._build_zone_cards(
                    spec.discard,
                    zone=Zone.DISCARD,
                    seen_ids=seen_ids,
                    default_owner=spec.player_id,
                )
            )
            built_instances.extend(
                self._build_board_cards(
                    cards_by_row=(
                        (Row.CLOSE, spec.board.close),
                        (Row.RANGED, spec.board.ranged),
                        (Row.SIEGE, spec.board.siege),
                    ),
                    zone=Zone.BATTLEFIELD,
                    seen_ids=seen_ids,
                    default_owner=spec.player_id,
                    battlefield_side=spec.player_id,
                )
            )
        built_instances.extend(
            self._build_board_cards(
                cards_by_row=(
                    (Row.CLOSE, self._weather.close),
                    (Row.RANGED, self._weather.ranged),
                    (Row.SIEGE, self._weather.siege),
                ),
                zone=Zone.WEATHER,
                seen_ids=seen_ids,
                default_owner=PLAYER_ONE_ID,
            )
        )
        return tuple(built_instances)

    def _build_zone_cards(
        self,
        cards: tuple[ScenarioCard, ...],
        *,
        zone: Zone,
        seen_ids: set[str],
        default_owner: PlayerId,
    ) -> tuple[CardInstance, ...]:
        return tuple(
            self._build_card_instance(
                card,
                zone=zone,
                seen_ids=seen_ids,
                default_owner=default_owner,
            )
            for card in cards
        )

    def _build_board_cards(
        self,
        *,
        cards_by_row: tuple[tuple[Row, tuple[ScenarioCard, ...]], ...],
        zone: Zone,
        seen_ids: set[str],
        default_owner: PlayerId,
        battlefield_side: PlayerId | None = None,
    ) -> tuple[CardInstance, ...]:
        return tuple(
            self._build_card_instance(
                card,
                zone=zone,
                row=row,
                battlefield_side=battlefield_side,
                seen_ids=seen_ids,
                default_owner=default_owner,
            )
            for row, cards in cards_by_row
            for card in cards
        )

    def _build_card_instance(
        self,
        card: ScenarioCard,
        *,
        zone: Zone,
        seen_ids: set[str],
        default_owner: PlayerId,
        row: Row | None = None,
        battlefield_side: PlayerId | None = None,
    ) -> CardInstance:
        if card.instance_id in seen_ids:
            raise ValueError(f"Duplicate scenario card instance id: {card.instance_id}")
        seen_ids.add(card.instance_id)
        return make_card_instance(
            instance_id=card.instance_id,
            definition_id=card.definition_id,
            owner=card.owner or default_owner,
            zone=zone,
            row=row,
            battlefield_side=battlefield_side,
        )


def _player_id(player_id: str | PlayerId) -> PlayerId:
    return PlayerId(str(player_id))


def _faction_id(faction: str | FactionId) -> FactionId:
    return FactionId(str(faction))


def _leader_id(leader_id: str | LeaderId) -> LeaderId:
    return LeaderId(str(leader_id))
