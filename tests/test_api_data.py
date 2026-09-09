from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.intelpark.api import BASE_URL, IntelparkApiClient

OBJECTS = f"{BASE_URL}v1/old_person_v2/get_objects"
GATES = f"{BASE_URL}v1/old_person_v2/get_gates"
OPEN = f"{BASE_URL}v1/old_person_v2/open_gate"
CAMERAS = f"{BASE_URL}v1/old_person_v2/get_cameras"


def _client(hass):
    return IntelparkApiClient(async_get_clientsession(hass), phone="7900", hash_="H")


async def test_get_objects(hass, aioclient_mock):
    # реальный ответ get_objects использует ключ "id" (строка), не "oid"
    aioclient_mock.get(
        OBJECTS,
        json=[{"id": "743", "name": "Дом", "balance": "0.00", "passesCount": 20}],
    )
    places = await _client(hass).async_get_objects()
    assert places[0].oid == 743 and places[0].name == "Дом"


async def test_get_objects_oid_fallback(hass, aioclient_mock):
    # запасной ключ "oid" всё ещё поддерживается
    aioclient_mock.get(OBJECTS, json=[{"oid": 7, "name": "Дача", "balance": "10"}])
    places = await _client(hass).async_get_objects()
    assert places[0].oid == 7


async def test_get_cameras_lenient_control_chars(hass, aioclient_mock):
    # сервер при пустом списке камер кладёт в message HTML с сырыми переводами
    # строк -> строгий json.loads падает; клиент должен разобрать (strict=False).
    aioclient_mock.get(
        CAMERAS, text='{"list": [], "message": "<html>\n  no cameras\n</html>"}'
    )
    cams = await _client(hass).async_get_cameras()
    assert cams == []


async def test_get_gates_flattens(hass, aioclient_mock):
    aioclient_mock.get(
        GATES,
        json=[
            {"oid": 7, "name": "Дом", "gates": [{"gid": "1", "name": "Шлагбаум"}]},
            {"oid": 8, "name": "Дача", "gates": [{"gid": "2", "name": "Ворота"}]},
        ],
    )
    gates = await _client(hass).async_get_gates()
    assert {g.gid for g in gates} == {"1", "2"}
    assert next(g for g in gates if g.gid == "1").object_name == "Дом"


async def test_open_gate(hass, aioclient_mock):
    aioclient_mock.get(OPEN, json={"success": True})
    await _client(hass).async_open_gate(42)
    method, url, *_ = aioclient_mock.mock_calls[0]
    assert "open_gate" in str(url)
    assert "gateId=42" in str(url)


async def test_authed_query_params(hass, aioclient_mock):
    aioclient_mock.get(OBJECTS, json=[])
    await _client(hass).async_get_objects()
    url = str(aioclient_mock.mock_calls[0][1])
    assert "client=3.6.2" in url
    assert "phone=7900" in url
    assert "hash=H" in url


async def test_get_cameras(hass, aioclient_mock):
    aioclient_mock.get(
        CAMERAS,
        json={
            "auth": "ok",
            "message": "",
            "list": [
                {
                    "camId": "c1",
                    "camName": "Двор",
                    "objectName": "Дом",
                    "snapshot": "https://v/c1/s.jpg",
                    "stream": "https://v/c1",
                    "streamToken": "T",
                    "streamTokenValidTill": 1,
                }
            ],
        },
    )
    cams = await _client(hass).async_get_cameras()
    assert cams[0].cam_id == "c1"


async def test_get_camera_single(hass, aioclient_mock):
    aioclient_mock.get(
        CAMERAS,
        json={
            "camId": "c1",
            "camName": "Двор",
            "objectName": "Дом",
            "snapshot": "https://v/c1/s.jpg",
            "stream": "https://v/c1",
            "streamToken": "T2",
            "streamTokenValidTill": 999,
        },
    )
    cam = await _client(hass).async_get_camera("c1")
    assert cam.stream_token == "T2"
    assert "camId=c1" in str(aioclient_mock.mock_calls[0][1])
