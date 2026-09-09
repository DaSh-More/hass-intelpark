"""Общие фикстуры тестов."""
import sys
import types

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

# HA 2026.2 безусловно импортирует пакет PyTurboJPEG (модуль `turbojpeg`)
# в homeassistant.components.camera.img_util — это опциональный
# JPEG-downscale helper самого HA, не используемый платформой intelpark
# (мы не запрашиваем масштабирование снимков). В обычной установке HA
# ставит его сам при первой настройке компонента "camera"; тестовый
# runner (pytest-homeassistant-custom-component) эту установку не
# выполняет, а пакет намеренно не добавлен в requirements-test.txt.
# Без заглушки `from homeassistant.components.camera import Camera`
# (нужный нам базовый класс) падает с ModuleNotFoundError и ломает
# настройку camera-платформы. Заглушка не устанавливает никакой пакет —
# только фиктивный модуль в sys.modules на время тестов.
# Ожидаемый побочный эффект заглушки: в логах теста появляется безобидная
# строка `ERROR ... Error loading libturbojpeg; Camera snapshot performance
# will be sub-optimal` — это собственный TurboJPEGSingleton HA перехватывает
# нашу RuntimeError при попытке создать TurboJPEG() и просто отключает
# даунскейлинг; тест из-за этого не падает, пугаться этой строки не нужно.
try:
    import turbojpeg  # noqa: F401
except ModuleNotFoundError:
    _stub = types.ModuleType("turbojpeg")

    class _StubTurboJPEG:  # pragma: no cover - платформой intelpark не вызывается
        def __init__(self, *args, **kwargs):
            raise RuntimeError("turbojpeg недоступен: тестовая заглушка")

    _stub.TurboJPEG = _StubTurboJPEG
    sys.modules["turbojpeg"] = _stub


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Разрешить загрузку custom_components в тестах."""
    yield
