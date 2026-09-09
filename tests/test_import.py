"""Скелет загружается и константы на месте."""
from custom_components.intelpark.const import BASE_URL, CLIENT, DOMAIN


def test_constants():
    assert DOMAIN == "intelpark"
    assert CLIENT == "3.6.2"
    assert BASE_URL.endswith("/api/")
