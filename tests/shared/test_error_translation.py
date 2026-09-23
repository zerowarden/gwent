from gwent_shared.error_translation import recover_exception


def test_recover_exception_returns_none_fallback() -> None:
    missing_values: dict[str, str] = {}

    result = recover_exception(
        lambda: missing_values["missing"],
        KeyError,
        lambda _exc: None,
    )

    assert result is None


def test_recover_exception_returns_operation_result_without_error() -> None:
    result = recover_exception(lambda: "value", KeyError, lambda _exc: None)

    assert result == "value"
