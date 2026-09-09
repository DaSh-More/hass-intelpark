import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.intelpark.api import (
    BASE_URL,
    Camera,
    IntelparkApiClient,
    IntelparkConnectionError,
    IntelparkError,
)

PASS = f"{BASE_URL}v1/old_person_v2/pass"
NOTIFICATIONS = f"{BASE_URL}v1/old_person_v2/notifications"
SET_NOTIFICATION_VIEWED = f"{BASE_URL}v1/old_person_v2/set_notification_viewed"
CAMERAS = f"{BASE_URL}v1/old_person_v2/get_cameras"
OBJECTS = f"{BASE_URL}v1/old_person_v2/get_objects"
ARCHIVE_URL = "https://v/c1/archive-100-60.mp4"
SNAPSHOT_URL = "https://v/c1/s.jpg"


def _client(hass):
    return IntelparkApiClient(async_get_clientsession(hass), phone="7900", hash_="H")


async def test_get_passes(hass, aioclient_mock):
    aioclient_mock.get(PASS, json=[{"id": 1, "phone": "79161234567"}])
    passes = await _client(hass).async_get_passes()
    assert passes == [{"id": 1, "phone": "79161234567"}]


async def test_get_notifications(hass, aioclient_mock):
    aioclient_mock.get(
        NOTIFICATIONS, json=[{"notificationId": "n1", "notification": "hi"}]
    )
    notifications = await _client(hass).async_get_notifications()
    assert notifications == [{"notificationId": "n1", "notification": "hi"}]


async def test_get_notifications_lenient_control_chars(hass, aioclient_mock):
    # тексты уведомлений многострочные — сырые переводы строк внутри JSON-строки;
    # клиент должен разобрать это (strict=False), а не падать.
    aioclient_mock.get(
        NOTIFICATIONS,
        text='[{"notificationId": "10432", "notification": "Соседи!\nЗавтра сбор."}]',
    )
    notifications = await _client(hass).async_get_notifications()
    assert notifications[0]["notificationId"] == "10432"
    assert "\n" in notifications[0]["notification"]


async def test_add_pass(hass, aioclient_mock):
    aioclient_mock.put(PASS, json={"id": 5})
    result = await _client(hass).async_add_pass({"phone": "79161234567", "note": "x"})
    assert result == {"id": 5}
    method, *_ = aioclient_mock.mock_calls[0]
    assert method.lower() == "put"


async def test_remove_pass(hass, aioclient_mock):
    aioclient_mock.delete(PASS, json={"success": True})
    await _client(hass).async_remove_pass(5)
    method, url, *_ = aioclient_mock.mock_calls[0]
    assert method.lower() == "delete"
    assert "id=5" in str(url)


async def test_set_notification_viewed(hass, aioclient_mock):
    aioclient_mock.put(SET_NOTIFICATION_VIEWED, json={"success": True})
    await _client(hass).async_set_notification_viewed("n1")
    method, url, *_ = aioclient_mock.mock_calls[0]
    assert method.lower() == "put"
    assert "id=n1" in str(url)


async def test_remove_notification(hass, aioclient_mock):
    aioclient_mock.delete(NOTIFICATIONS, json={"success": True})
    await _client(hass).async_remove_notification("n1")
    method, url, *_ = aioclient_mock.mock_calls[0]
    assert method.lower() == "delete"
    assert "id=n1" in str(url)


async def test_download_archive(hass, aioclient_mock):
    aioclient_mock.get(ARCHIVE_URL, content=b"videobytes")
    camera = Camera(
        cam_id="c1",
        name="Двор",
        object_name="Дом",
        snapshot="https://v/c1/s.jpg",
        stream="https://v/c1",
        stream_token="T",
        stream_token_valid_till=1,
    )
    data = await _client(hass).async_download_archive(camera, "100", "60")
    assert data == b"videobytes"


async def test_fetch_snapshot(hass, aioclient_mock):
    aioclient_mock.get(SNAPSHOT_URL, content=b"jpegbytes")
    data = await _client(hass).async_fetch_snapshot(SNAPSHOT_URL)
    assert data == b"jpegbytes"


async def test_malformed_camera_raises_intelpark_error(hass, aioclient_mock):
    aioclient_mock.get(CAMERAS, json={"list": [{"camName": "x"}]})
    with pytest.raises(IntelparkError):
        await _client(hass).async_get_cameras()


async def test_404_raises_intelpark_error(hass, aioclient_mock):
    aioclient_mock.get(OBJECTS, status=404)
    with pytest.raises(IntelparkError) as exc_info:
        await _client(hass).async_get_objects()
    assert exc_info.type is IntelparkError


async def test_500_raises_intelpark_connection_error(hass, aioclient_mock):
    aioclient_mock.get(OBJECTS, status=500)
    with pytest.raises(IntelparkConnectionError):
        await _client(hass).async_get_objects()
