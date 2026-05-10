from gwent_engine.cards import CardRegistry
from gwent_engine.core import CardType, EffectSourceCategory, Zone
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import GameState, PlayerState

HERO_IMMUNE_SOURCE_CATEGORIES: frozenset[EffectSourceCategory] = frozenset(
    {
        EffectSourceCategory.SPECIAL_CARD,
        EffectSourceCategory.UNIT_ABILITY,
        EffectSourceCategory.LEADER_ABILITY,
    }
)


def is_hero(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    return definition.card_type == CardType.UNIT and definition.is_hero


def can_affect_card(
    state: GameState,
    card_registry: CardRegistry,
    *,
    source_category: EffectSourceCategory,
    target_card_id: CardInstanceId,
) -> bool:
    if source_category in HERO_IMMUNE_SOURCE_CATEGORIES and is_hero(
        state,
        card_registry,
        target_card_id,
    ):
        return False
    return True


def can_target_for_decoy(
    state: GameState,
    card_registry: CardRegistry,
    *,
    player: PlayerState,
    target_card_id: CardInstanceId,
) -> bool:
    if target_card_id not in player.rows.all_cards():
        return False
    target_card = state.card(target_card_id)
    if target_card.zone != Zone.BATTLEFIELD or target_card.battlefield_side != player.player_id:
        return False
    definition = card_registry.get(target_card.definition_id)
    return definition.card_type == CardType.UNIT and can_affect_card(
        state,
        card_registry,
        source_category=EffectSourceCategory.SPECIAL_CARD,
        target_card_id=target_card_id,
    )


def can_target_for_medic(
    state: GameState,
    card_registry: CardRegistry,
    *,
    player: PlayerState,
    target_card_id: CardInstanceId,
) -> bool:
    if target_card_id not in player.discard:
        return False
    definition = card_registry.get(state.card(target_card_id).definition_id)
    return definition.card_type == CardType.UNIT and can_affect_card(
        state,
        card_registry,
        source_category=EffectSourceCategory.UNIT_ABILITY,
        target_card_id=target_card_id,
    )


def eligible_destroyable_unit_ids(
    state: GameState,
    card_registry: CardRegistry,
    candidate_card_ids: tuple[CardInstanceId, ...],
    *,
    source_category: EffectSourceCategory,
) -> tuple[CardInstanceId, ...]:
    return tuple(
        card_id
        for card_id in candidate_card_ids
        if card_registry.get(state.card(card_id).definition_id).card_type == CardType.UNIT
        and can_affect_card(
            state,
            card_registry,
            source_category=source_category,
            target_card_id=card_id,
        )
    )
