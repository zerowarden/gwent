from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from gwent_shared.error_translation import translate_mapping_key

from gwent_engine.core.enums import (
    ChoiceKind,
    ChoiceSourceKind,
    FactionId,
    GameStatus,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.errors import UnknownCardInstanceError, UnknownPlayerError
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    PlayerId,
)


@dataclass(frozen=True, slots=True)
class CardInstance:
    instance_id: CardInstanceId
    definition_id: CardDefinitionId
    owner: PlayerId
    zone: Zone
    row: Row | None = None
    battlefield_side: PlayerId | None = None

    def __post_init__(self) -> None:
        self._validate_row_requirement()
        self._validate_weather_side()
        self._validate_non_battlefield_position()

    def _validate_row_requirement(self) -> None:
        if self.zone in {Zone.BATTLEFIELD, Zone.WEATHER} and self.row is None:
            raise ValueError("Battlefield and weather card instances must declare a row.")

    def _validate_weather_side(self) -> None:
        if self.zone == Zone.WEATHER and self.battlefield_side is not None:
            raise ValueError("Weather card instances cannot declare a battlefield_side.")

    def _validate_non_battlefield_position(self) -> None:
        if self.zone in {Zone.BATTLEFIELD, Zone.WEATHER}:
            return
        if self.row is not None:
            raise ValueError("Only battlefield and weather card instances may declare a row.")
        if self.battlefield_side is not None:
            raise ValueError("Only battlefield card instances may declare a battlefield_side.")


@dataclass(frozen=True, slots=True)
class RowState:
    close: tuple[CardInstanceId, ...] = ()
    ranged: tuple[CardInstanceId, ...] = ()
    siege: tuple[CardInstanceId, ...] = ()

    def __post_init__(self) -> None:
        all_cards = self.all_cards()
        if len(set(all_cards)) != len(all_cards):
            raise ValueError("A row state cannot contain duplicate card instance ids.")

    def cards_for(self, row: Row) -> tuple[CardInstanceId, ...]:
        if row == Row.CLOSE:
            return self.close
        if row == Row.RANGED:
            return self.ranged
        return self.siege

    def all_cards(self) -> tuple[CardInstanceId, ...]:
        return self.close + self.ranged + self.siege


@dataclass(frozen=True, slots=True)
class LeaderState:
    leader_id: LeaderId
    used: bool = False
    disabled: bool = False
    horn_row: Row | None = None


@dataclass(frozen=True, slots=True)
class PendingAvengerSummon:
    source_card_instance_id: CardInstanceId
    summoned_definition_id: CardDefinitionId
    owner: PlayerId
    battlefield_side: PlayerId
    row: Row


@dataclass(frozen=True, slots=True)
class PendingChoice:
    choice_id: ChoiceId
    player_id: PlayerId
    kind: ChoiceKind
    source_kind: ChoiceSourceKind
    source_card_instance_id: CardInstanceId | None = None
    source_leader_id: LeaderId | None = None
    legal_target_card_instance_ids: tuple[CardInstanceId, ...] = ()
    legal_rows: tuple[Row, ...] = ()
    min_selections: int = 1
    max_selections: int = 1
    source_row: Row | None = None

    def __post_init__(self) -> None:
        if self.source_card_instance_id is None and self.source_leader_id is None:
            raise ValueError("PendingChoice must reference a source card or leader.")
        if self.min_selections < 0:
            raise ValueError("PendingChoice min_selections cannot be negative.")
        if self.max_selections < self.min_selections:
            raise ValueError("PendingChoice max_selections cannot be below min_selections.")
        if len(set(self.legal_target_card_instance_ids)) != len(
            self.legal_target_card_instance_ids
        ):
            raise ValueError("PendingChoice legal target ids must be unique.")
        if len(set(self.legal_rows)) != len(self.legal_rows):
            raise ValueError("PendingChoice legal rows must be unique.")


@dataclass(frozen=True, slots=True)
class PlayerState:
    player_id: PlayerId
    faction: FactionId
    leader: LeaderState
    deck: tuple[CardInstanceId, ...]
    hand: tuple[CardInstanceId, ...]
    discard: tuple[CardInstanceId, ...]
    rows: RowState
    gems_remaining: int = 2
    round_wins: int = 0
    has_passed: bool = False

    def __post_init__(self) -> None:
        if self.gems_remaining < 0 or self.gems_remaining > 2:
            raise ValueError("gems_remaining must stay within 0..2.")
        if self.round_wins < 0 or self.round_wins > 2:
            raise ValueError("round_wins must stay within 0..2.")
        all_cards = self.all_card_ids()
        if len(set(all_cards)) != len(all_cards):
            raise ValueError("A player state cannot reference the same card instance twice.")

    def all_card_ids(self) -> tuple[CardInstanceId, ...]:
        return self.deck + self.hand + self.discard + self.rows.all_cards()


@dataclass(frozen=True, slots=True)
class GameState:
    game_id: GameId
    players: tuple[PlayerState, PlayerState]
    card_instances: tuple[CardInstance, ...]
    weather: RowState = RowState()
    pending_avenger_summons: tuple[PendingAvengerSummon, ...] = ()
    pending_choice: PendingChoice | None = None
    current_player: PlayerId | None = None
    starting_player: PlayerId | None = None
    round_starter: PlayerId | None = None
    round_number: int = 1
    phase: Phase = Phase.NOT_STARTED
    status: GameStatus = GameStatus.NOT_STARTED
    match_winner: PlayerId | None = None
    event_counter: int = 0
    generated_card_counter: int = 0
    rng_seed: int | None = None
    _card_index: Mapping[CardInstanceId, CardInstance] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _player_index: Mapping[PlayerId, PlayerState] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _player_ids: frozenset[PlayerId] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _derived_cache: dict[object, object] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if len(self.players) != 2:
            raise ValueError("GameState requires exactly two players.")
        player_index = {player.player_id: player for player in self.players}
        player_ids = frozenset(player_index)
        if len(player_ids) != len(self.players):
            raise ValueError("GameState player ids must be unique.")
        card_index = {card.instance_id: card for card in self.card_instances}
        if len(card_index) != len(self.card_instances):
            raise ValueError("GameState card instance ids must be unique.")
        if self.round_number < 1:
            raise ValueError("round_number must be positive.")
        if self.event_counter < 0:
            raise ValueError("event_counter cannot be negative.")
        if self.generated_card_counter < 0:
            raise ValueError("generated_card_counter cannot be negative.")

        for player_id in (
            self.pending_choice.player_id if self.pending_choice is not None else None,
            self.current_player,
            self.starting_player,
            self.round_starter,
            self.match_winner,
            *(summon.owner for summon in self.pending_avenger_summons),
            *(summon.battlefield_side for summon in self.pending_avenger_summons),
            *(card.battlefield_side for card in self.card_instances),
        ):
            if player_id is not None and player_id not in player_ids:
                raise ValueError(f"Unknown player id on GameState: {player_id!r}")

        if self.pending_choice is not None:
            for card_id in (
                self.pending_choice.source_card_instance_id,
                *self.pending_choice.legal_target_card_instance_ids,
            ):
                if card_id is not None and card_id not in card_index:
                    raise ValueError(f"Unknown card id on PendingChoice: {card_id!r}")

        object.__setattr__(self, "_card_index", MappingProxyType(card_index))
        object.__setattr__(self, "_player_index", MappingProxyType(player_index))
        object.__setattr__(self, "_player_ids", player_ids)
        object.__setattr__(self, "_derived_cache", {})

    def player_ids(self) -> frozenset[PlayerId]:
        return self._player_ids

    @property
    def battlefield_weather(self) -> RowState:
        return self.weather

    def player(self, player_id: PlayerId) -> PlayerState:
        return translate_mapping_key(self._player_index, player_id, UnknownPlayerError)

    def card(self, instance_id: CardInstanceId) -> CardInstance:
        return translate_mapping_key(self._card_index, instance_id, UnknownCardInstanceError)

    def cached_value(self, key: object) -> object | None:
        return self._derived_cache.get(key)

    def cache_value(self, key: object, value: object) -> None:
        self._derived_cache[key] = value

    def cached_or_compute[T](self, key: object, factory: Callable[[], T]) -> T:
        cached_value = self.cached_value(key)
        if cached_value is not None:
            return cast(T, cached_value)
        value = factory()
        self.cache_value(key, value)
        return value
