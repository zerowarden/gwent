from random import Random
from typing import Protocol, final, override

from gwent_engine.core.ids import CardInstanceId


class SupportsRandom(Protocol):
    def shuffle(self, cards: list[CardInstanceId]) -> None:
        """Shuffle cards in place."""
        ...

    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        """Choose one card deterministically from the provided options."""
        ...


@final
class SeededRandom(SupportsRandom):
    def __init__(self, seed: int | None = None) -> None:
        self._random = Random(seed)

    @override
    def shuffle(self, cards: list[CardInstanceId]) -> None:
        self._random.shuffle(cards)

    @override
    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        return self._random.choice(cards)
