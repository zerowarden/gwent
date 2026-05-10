from random import Random
from typing import Protocol, final

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


class IdentityRandom:
    """Deterministic RNG that preserves deck order and chooses the first option."""

    def shuffle(self, cards: list[CardInstanceId]) -> None:
        _ = cards
        return None

    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        return cards[0]


@final
class SeededRandom:
    def __init__(self, seed: int | None = None) -> None:
        self._random = Random(seed)

    def shuffle(self, cards: list[CardInstanceId]) -> None:
        self._random.shuffle(cards)

    def choice(self, cards: tuple[CardInstanceId, ...]) -> CardInstanceId:
        return self._random.choice(cards)
