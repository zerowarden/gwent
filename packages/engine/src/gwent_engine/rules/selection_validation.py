from collections.abc import Iterable

from gwent_engine.core.errors import IllegalActionError


def validate_distinct_selections(
    selections: Iterable[object],
    *,
    duplicate_message: str,
) -> tuple[object, ...]:
    normalized = tuple(selections)
    if len(set(normalized)) != len(normalized):
        raise IllegalActionError(duplicate_message)
    return normalized


def validate_selection_count(
    selections: Iterable[object],
    *,
    min_selections: int,
    max_selections: int,
    invalid_count_message: str,
) -> tuple[object, ...]:
    normalized = tuple(selections)
    if not min_selections <= len(normalized) <= max_selections:
        raise IllegalActionError(invalid_count_message)
    return normalized


def validate_legal_selections(
    selections: Iterable[object],
    *,
    legal_values: Iterable[object],
    illegal_message: str,
) -> tuple[object, ...]:
    normalized = tuple(selections)
    legal = set(legal_values)
    if any(value not in legal for value in normalized):
        raise IllegalActionError(illegal_message)
    return normalized
