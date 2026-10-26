"""Константы интеграции Intelpark («Дворецкий»)."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "intelpark"

BASE_URL = "https://core.internal.intelpark.ru/api/"
CLIENT = "3.6.2"  # значение query-параметра client (версия приложения)

CONF_PHONE = "phone"
CONF_HASH = "hash"

CONF_GATE_PREVIEW_SOURCE = "gate_preview_source"
PREVIEW_SOURCE_STREAM = "stream"
PREVIEW_SOURCE_SNAPSHOT = "snapshot"
GATE_PREVIEW_SOURCES = (PREVIEW_SOURCE_STREAM, PREVIEW_SOURCE_SNAPSHOT)
DEFAULT_GATE_PREVIEW_SOURCE = PREVIEW_SOURCE_STREAM

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = 15  # секунд
TOKEN_REFRESH_MARGIN = 60  # обновлять токен стрима за N секунд до истечения

EVENT_NOTIFICATION = f"{DOMAIN}_notification"

MANUFACTURER = "Intelpark / Дворецкий"
