from __future__ import annotations

from collections.abc import Sequence
from typing import final

from gwent_engine.ai.baseline import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
    get_base_profile_definition,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_SEARCH_CONFIG, SearchConfig
from gwent_engine.ai.search.engine import SearchEngine, build_search_engine
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    ResolveChoiceAction,
)
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.leaders import LeaderRegistry


@final
class SearchBot:
    def __init__(
        self,
        *,
        config: SearchConfig = DEFAULT_SEARCH_CONFIG,
        profile_definition: BaseProfileDefinition = DEFAULT_BASE_PROFILE,
        bot_id: str = "search_bot",
    ) -> None:
        self.bot_id = bot_id
        self.display_name = (
            "SearchBot"
            if profile_definition.profile_id == DEFAULT_BASE_PROFILE.profile_id
            else f"SearchBot[{profile_definition.profile_id}]"
        )
        self._engine: SearchEngine = build_search_engine(
            config=config,
            profile_definition=profile_definition,
            bot_id=bot_id,
        )

    @staticmethod
    def from_profile_id(*, bot_id: str, profile_id: str | None) -> SearchBot:
        if profile_id is None:
            return SearchBot(bot_id=bot_id)
        return SearchBot(
            bot_id=bot_id,
            profile_definition=get_base_profile_definition(profile_id),
        )

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        return self._engine.choose_mulligan(
            observation,
            legal_selections,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        result = self._engine.choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        return result.chosen_action

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        result = self._engine.choose_pending_choice(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        if not isinstance(result.chosen_action, ResolveChoiceAction):
            raise IllegalActionError("SearchBot pending choice requires ResolveChoiceAction.")
        return result.chosen_action
