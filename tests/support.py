from pathlib import Path
from typing import final, override

from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.randomness import SupportsRandom

PLAYER_ONE_ID = PlayerId("p1")
PLAYER_TWO_ID = PlayerId("p2")


def write_yaml_fixture(tmp_path: Path, filename: str, content: str) -> Path:
    path = tmp_path / filename
    _ = path.write_text(content.strip(), encoding="utf-8")
    return path


def choose_by_index(cards: tuple[CardInstanceId, ...], index: int) -> CardInstanceId:
    return cards[index % len(cards)]


class IdentityRandom(SupportsRandom):
    """Deterministic RNG that preserves deck order and chooses the first option."""

    @override
    def shuffle(self, cards: list[CardInstanceId]) -> None:
        _ = cards
        return None

    @override
    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        return cards[0]


@final
class IndexedRandom(IdentityRandom):
    def __init__(self, *, choice_index: int) -> None:
        self.choice_index: int = choice_index

    @override
    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        return choose_by_index(cards, self.choice_index)
