import pytest
from gwent_shared.error_translation import translate_mapping_key


class _MissingKeyError(Exception):
    pass


def test_translate_mapping_key_returns_existing_value() -> None:
    result = translate_mapping_key({"present": "value"}, "present", _MissingKeyError)

    assert result == "value"


def test_translate_mapping_key_raises_factory_error_for_missing_key() -> None:
    missing_values: dict[str, str] = {}

    with pytest.raises(_MissingKeyError):
        _ = translate_mapping_key(missing_values, "missing", _MissingKeyError)
