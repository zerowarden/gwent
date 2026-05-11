from random import Random
from typing import Protocol, final, override

from gwent_engine.core.ids import CardInstanceId


def choose_by_index(cards: tuple[CardInstanceId, ...], index: int) -> CardInstanceId:
    return cards[index % len(cards)]


class SupportsRandom(Protocol):
    def shuffle(self, cards: list[CardInstanceId]) -> None:
        """Shuffle cards in place."""
        ...

    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        """Choose one card deterministically from the provided options."""
        ...


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
class SeededRandom(SupportsRandom):
    def __init__(self, seed: int | None = None) -> None:
        self._random = Random(seed)

    @override
    def shuffle(self, cards: list[CardInstanceId]) -> None:
        self._random.shuffle(cards)

    @override
    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        return self._random.choice(cards)
