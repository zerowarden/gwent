from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from gwent_engine.ai.baseline.projection.board import current_public_board_projection
from gwent_engine.ai.baseline.projection.context import (
    PublicPlayerContext,
    active_weather_rows,
)
from gwent_engine.ai.baseline.projection.models import PublicBoardProjection
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardRegistry
from gwent_engine.core import Row


@dataclass(frozen=True)
class ProjectionResolverContext(PublicPlayerContext):
    """Shared cached public context for deterministic projection resolvers."""

    observation: PlayerObservation
    card_registry: CardRegistry

    @cached_property
    def current_board(self) -> PublicBoardProjection:
        return current_public_board_projection(self.observation, card_registry=self.card_registry)

    @cached_property
    def current_weather_rows(self) -> tuple[Row, ...]:
        return active_weather_rows(self.observation)
