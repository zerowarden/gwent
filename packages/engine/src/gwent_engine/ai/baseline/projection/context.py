from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from gwent_engine.ai.observations import (
    ObservedCard,
    PlayerObservation,
    PublicPlayerStateView,
)
from gwent_engine.core import Row
from gwent_engine.core.ids import PlayerId


@dataclass(frozen=True)
class PublicPlayerContext:
    observation: PlayerObservation

    @cached_property
    def viewer(self) -> PublicPlayerStateView:
        return viewer_public(self.observation)

    @cached_property
    def opponent(self) -> PublicPlayerStateView:
        return opponent_public(self.observation)

    @cached_property
    def halve_weather_penalty_sides(self) -> frozenset[PlayerId]:
        return frozenset(
            player.player_id
            for player in self.observation.public_state.players
            if player.leader.halves_weather_penalty
        )

    @cached_property
    def double_spy_strength_global(self) -> bool:
        return any(
            player.leader.doubles_spy_strength for player in self.observation.public_state.players
        )


def viewer_public(observation: PlayerObservation) -> PublicPlayerStateView:
    return _public_player(observation, viewer=True)


def opponent_public(observation: PlayerObservation) -> PublicPlayerStateView:
    return _public_player(observation, viewer=False)


def _public_player(
    observation: PlayerObservation,
    *,
    viewer: bool,
) -> PublicPlayerStateView:
    return next(
        player
        for player in observation.public_state.players
        if (player.player_id == observation.viewer_player_id) is viewer
    )


def active_weather_rows(observation: PlayerObservation) -> tuple[Row, ...]:
    return tuple(
        row
        for row, cards in (
            (Row.CLOSE, observation.public_state.battlefield_weather.close),
            (Row.RANGED, observation.public_state.battlefield_weather.ranged),
            (Row.SIEGE, observation.public_state.battlefield_weather.siege),
        )
        if cards
    )


def visible_battlefield_cards(
    observation: PlayerObservation,
) -> tuple[ObservedCard, ...]:
    cards: list[ObservedCard] = []
    for player in observation.public_state.players:
        cards.extend(player.rows.close)
        cards.extend(player.rows.ranged)
        cards.extend(player.rows.siege)
    return tuple(cards)
