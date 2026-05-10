from __future__ import annotations

from gwent_service.application.errors import (
    MulliganAlreadySubmittedError,
    MulliganSelectionError,
)
from gwent_service.domain.models import StagedMulliganSubmission


def stage_mulligan_submission(
    staged_mulligans: tuple[StagedMulliganSubmission, ...],
    submission: StagedMulliganSubmission,
    *,
    valid_engine_player_ids: frozenset[str],
) -> tuple[StagedMulliganSubmission, ...]:
    if submission.engine_player_id not in valid_engine_player_ids:
        raise MulliganSelectionError(
            f"Unknown engine player id {submission.engine_player_id!r} for mulligan staging."
        )
    if any(staged.engine_player_id == submission.engine_player_id for staged in staged_mulligans):
        raise MulliganAlreadySubmittedError(submission.engine_player_id)
    return (*staged_mulligans, submission)


def mulligan_submission_map(
    staged_mulligans: tuple[StagedMulliganSubmission, ...],
) -> dict[str, tuple[str, ...]]:
    return {
        submission.engine_player_id: submission.card_instance_ids for submission in staged_mulligans
    }


def mulligans_are_complete(
    staged_mulligans: tuple[StagedMulliganSubmission, ...],
    *,
    expected_count: int = 2,
) -> bool:
    return len(staged_mulligans) == expected_count
