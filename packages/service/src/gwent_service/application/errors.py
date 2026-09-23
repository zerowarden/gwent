from typing import ClassVar


class MatchServiceError(Exception):
    """Base error for gwent_service failures."""


class _SingleValueMatchServiceError(MatchServiceError):
    message_template: ClassVar[str]

    def __init__(self, value: str) -> None:
        super().__init__(self.message_template.format(value=value))


class MatchAlreadyExistsError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Match {value!r} already exists."


class MatchNotFoundError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Match {value!r} was not found."


class UnknownDeckError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Unknown deck {value!r}."


class MatchVersionConflictError(MatchServiceError):
    match_id: str
    expected_version: int
    actual_version: int

    def __init__(
        self,
        match_id: str,
        *,
        expected_version: int,
        actual_version: int,
    ) -> None:
        super().__init__(
            f"Stale match {match_id!r}: expected version {expected_version}, got {actual_version}."
        )
        self.match_id = match_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class UnknownMatchPlayerError(MatchServiceError):
    def __init__(self, service_player_id: str, match_id: str) -> None:
        super().__init__(f"Player {service_player_id!r} does not belong to match {match_id!r}.")


class MatchPhaseError(MatchServiceError):
    pass


class MulliganAlreadySubmittedError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Mulligan already submitted for engine player {value!r}."


class MulliganSelectionError(MatchServiceError):
    pass
