import pytest

from custom_components.intelpark.api import normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 (916) 123-45-67", "79161234567"),
        ("89161234567", "79161234567"),
        ("79161234567", "79161234567"),
        ("9161234567", "79161234567"),
    ],
)
def test_normalize_ok(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["123", "", "12345678901234"])
def test_normalize_bad(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)
