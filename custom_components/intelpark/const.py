"""Константы интеграции Intelpark («Дворецкий»)."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "intelpark"

BASE_URL = "https://core.internal.intelpark.ru/api/"
CLIENT = "3.6.2"  # значение query-параметра client (версия приложения)

CONF_PHONE = "phone"
CONF_HASH = "hash"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = 15  # секунд
TOKEN_REFRESH_MARGIN = 60  # обновлять токен стрима за N секунд до истечения

EVENT_NOTIFICATION = f"{DOMAIN}_notification"

MANUFACTURER = "Intelpark / Дворецкий"
