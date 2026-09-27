from gwent_engine.ai.baseline.features import dead_card_penalty
from gwent_engine.core import Row
from gwent_engine.core.ids import CardDefinitionId

from ..support import CARD_REGISTRY


def test_dead_card_penalty_counts_redundant_weather_and_clear_weather() -> None:
    definitions = (
        CARD_REGISTRY.get(CardDefinitionId("neutral_clear_weather")),
        CARD_REGISTRY.get(CardDefinitionId("neutral_biting_frost")),
    )

    assert dead_card_penalty(definitions) == 1
    assert dead_card_penalty(definitions, active_weather_rows=(Row.CLOSE,)) == 1
