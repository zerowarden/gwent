from __future__ import annotations

from typing import cast

import pytest
from gwent_evaluation import (
    DEFAULT_BOOTSTRAP,
    BootstrapConfig,
    CaseStatus,
    IntervalMethod,
    ScoredCase,
    compare_block_scores,
    compute_run_metrics,
)
from gwent_evaluation.metrics import summarize_scores

from tests.evaluation.support import (
    bool_field,
    float_field,
    int_field,
    load_metrics_fixture,
    str_field,
)


def test_complete_blocks_fixture_produces_exact_scores() -> None:
    fixture = load_metrics_fixture("complete-blocks.json")

    metrics = compute_run_metrics(fixture.cases)

    expected = fixture.expected
    assert metrics.planned == int_field(expected, "planned")
    assert metrics.executed == int_field(expected, "executed")
    assert metrics.completed == int_field(expected, "completed")
    assert metrics.failed == int_field(expected, "failed")
    assert metrics.missing == int_field(expected, "missing")
    assert metrics.candidate.wins == int_field(expected, "wins")
    assert metrics.candidate.draws == int_field(expected, "draws")
    assert metrics.candidate.losses == int_field(expected, "losses")
    assert metrics.candidate.score == float_field(expected, "score")
    assert metrics.balanced_score == float_field(expected, "balanced_score")
    assert metrics.complete_blocks == int_field(expected, "complete_blocks")
    assert metrics.total_blocks == int_field(expected, "total_blocks")
    assert metrics.interval.method is IntervalMethod(str_field(expected, "interval_method"))
    assert metrics.valid is bool_field(expected, "valid")
    assert len(metrics.strata) == int_field(expected, "strata_count")


def test_failures_and_missing_never_enter_denominators() -> None:
    fixture = load_metrics_fixture("failures-and-missing.json")

    metrics = compute_run_metrics(fixture.cases)

    expected = fixture.expected
    assert metrics.executed == int_field(expected, "executed")
    assert metrics.completed == int_field(expected, "completed")
    assert metrics.failed == int_field(expected, "failed")
    assert metrics.missing == int_field(expected, "missing")
    assert metrics.candidate.completed == int_field(expected, "completed")
    assert metrics.candidate.wins == int_field(expected, "wins")
    assert metrics.candidate.draws == int_field(expected, "draws")
    assert metrics.candidate.losses == int_field(expected, "losses")
    assert metrics.candidate.score == float_field(expected, "score")
    assert metrics.balanced_score is None
    assert metrics.complete_blocks == 0
    assert metrics.interval.method is IntervalMethod.INSUFFICIENT_SAMPLE
    assert metrics.valid is False
    assert len(metrics.validity_reasons) == int_field(expected, "validity_reasons")


def test_bootstrap_interval_is_deterministic_and_bounded() -> None:
    fixture = load_metrics_fixture("complete-blocks.json")

    first = compute_run_metrics(fixture.cases)
    second = compute_run_metrics(fixture.cases)

    assert first.interval == second.interval
    assert first.interval.method is IntervalMethod.BLOCK_BOOTSTRAP
    assert first.interval.blocks == 8
    assert first.interval.resamples == DEFAULT_BOOTSTRAP.resamples
    lower = first.interval.lower
    upper = first.interval.upper
    balanced = first.balanced_score
    assert lower is not None
    assert upper is not None
    assert balanced is not None
    assert lower <= balanced <= upper


def test_tiny_sample_reports_insufficient_sample() -> None:
    fixture = load_metrics_fixture("complete-blocks.json")
    cases = fixture.cases[:6]

    metrics = compute_run_metrics(cases)

    assert metrics.complete_blocks == 2
    assert metrics.interval.method is IntervalMethod.INSUFFICIENT_SAMPLE
    assert metrics.interval.lower is None
    assert metrics.interval.upper is None


def test_bootstrap_config_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="resamples"):
        _ = BootstrapConfig(resamples=0)
    with pytest.raises(ValueError, match="confidence"):
        _ = BootstrapConfig(confidence_level=1.0)
    with pytest.raises(ValueError, match="minimum block"):
        _ = BootstrapConfig(minimum_blocks=1)


def test_paired_blocks_fixture_produces_exact_differences() -> None:
    fixture = load_metrics_fixture("paired-blocks.json")

    comparison = compare_block_scores(fixture.reference, fixture.candidate)

    expected = fixture.expected
    assert len(comparison.blocks) == int_field(expected, "paired_blocks")
    assert comparison.reference_score == float_field(expected, "reference_score")
    assert comparison.candidate_score == float_field(expected, "candidate_score")
    assert comparison.mean_difference == float_field(expected, "mean_difference")
    differences = [block.difference for block in comparison.blocks]
    expected_differences = cast(list[object], expected["differences"])
    assert differences == [float(cast(float, value)) for value in expected_differences]
    assert comparison.interval.method is IntervalMethod(str_field(expected, "interval_method"))


def test_paired_comparison_ignores_incomplete_blocks() -> None:
    fixture = load_metrics_fixture("paired-blocks.json")
    broken = tuple(
        case
        if case.case_id != "n2"
        else ScoredCase(
            case_id=case.case_id,
            block_id=case.block_id,
            status=CaseStatus.FAILED,
            score=None,
            strata=case.strata,
        )
        for case in fixture.candidate
    )

    comparison = compare_block_scores(fixture.reference, broken)

    assert [block.block_id for block in comparison.blocks] == [
        "block-1",
        "block-3",
        "block-4",
    ]


def test_invalid_score_is_rejected() -> None:
    with pytest.raises(ValueError, match="Candidate score"):
        _ = summarize_scores([1.0, 0.7])


def test_empty_scores_have_no_mean() -> None:
    summary = summarize_scores([])

    assert summary.completed == 0
    assert summary.score is None
