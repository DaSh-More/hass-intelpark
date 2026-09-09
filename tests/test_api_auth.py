import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.intelpark.api import (
    BASE_URL,
    IntelparkApiClient,
    IntelparkAuthError,
    IntelparkError,
)

CODE_URL = f"{BASE_URL}v1/old_person_v2/get_auth_code"
HASH_URL = f"{BASE_URL}v1/old_person_v2/get_auth_hash"
CHECK_URL = f"{BASE_URL}v1/old_person_v2/check_auth"


async def test_send_code_ok(hass, aioclient_mock):
    aioclient_mock.get(CODE_URL, json={"sent": True, "successMessage": "ok", "errors": []})
    client = IntelparkApiClient(async_get_clientsession(hass))
    await client.async_send_code("79161234567")
    assert aioclient_mock.call_count == 1
    assert "phone=79161234567" in str(aioclient_mock.mock_calls[0][1])


async def test_send_code_error(hass, aioclient_mock):
    aioclient_mock.get(CODE_URL, json={"sent": False, "errors": ["Неверный номер"]})
    client = IntelparkApiClient(async_get_clientsession(hass))
    with pytest.raises(IntelparkError):
        await client.async_send_code("79161234567")


async def test_send_code_not_sent_no_errors(hass, aioclient_mock):
    aioclient_mock.get(CODE_URL, json={"sent": False, "successMessage": "Лимит SMS"})
    client = IntelparkApiClient(async_get_clientsession(hass))
    with pytest.raises(IntelparkError):
        await client.async_send_code("79161234567")


async def test_get_hash_ok(hass, aioclient_mock):
    aioclient_mock.get(HASH_URL, json={"phone": "79161234567", "hash": "H", "errors": []})
    client = IntelparkApiClient(async_get_clientsession(hass))
    phone, hash_ = await client.async_get_hash("79161234567", "1234")
    assert (phone, hash_) == ("79161234567", "H")
    url = str(aioclient_mock.mock_calls[0][1])
    assert "phone=79161234567" in url and "code=1234" in url


async def test_get_hash_bad_code(hass, aioclient_mock):
    aioclient_mock.get(HASH_URL, json={"errors": ["Неверный код"]})
    client = IntelparkApiClient(async_get_clientsession(hass))
    with pytest.raises(IntelparkError):
        await client.async_get_hash("79161234567", "0000")


async def test_check_auth_401(hass, aioclient_mock):
    aioclient_mock.get(CHECK_URL, status=403)
    client = IntelparkApiClient(async_get_clientsession(hass), phone="79161234567", hash_="BAD")
    with pytest.raises(IntelparkAuthError):
        await client.async_check_auth()
