from custom_components.intelpark.api import AccountPlace, Camera, Gate


def test_camera_from_json_and_urls():
    cam = Camera.from_json(
        {
            "camId": "c1",
            "camName": "Двор",
            "objectName": "Мой дом",
            "snapshot": "https://video0.intelpark.ru/c1/snap.jpg",
            "stream": "https://video0.intelpark.ru/c1",
            "streamToken": "TOK",
            "streamTokenValidTill": 1893456000,
        }
    )
    assert cam.cam_id == "c1"
    assert cam.name == "Двор"
    assert cam.object_name == "Мой дом"
    assert cam.stream_url() == "https://video0.intelpark.ru/c1/index.m3u8?token=TOK"
    assert (
        cam.archive_mp4_url("100", "60")
        == "https://video0.intelpark.ru/c1/archive-100-60.mp4?token=TOK"
    )


def test_gate_from_json():
    gate = Gate.from_json(
        {
            "gid": "42",
            "name": "Шлагбаум",
            "liveUrl": "https://x/live",
            "liveCam": "1",
            "snapshotImage": "https://x/still.jpg",
        },
        object_id=7,
        object_name="Мой дом",
    )
    assert gate.gid == "42"
    assert gate.gate_id_int == 42
    assert gate.object_name == "Мой дом"
    assert gate.live_url == "https://x/live"
    assert gate.live_cam == "1"
    assert gate.snapshot_image == "https://x/still.jpg"
    assert gate.live_stream_url() == "https://x/live/mono.m3u8"


def test_account_place_from_json():
    place = AccountPlace.from_json(
        {"oid": 7, "name": "Мой дом", "balance": "123.45"}
    )
    assert place.oid == 7
    assert place.name == "Мой дом"
    assert place.balance == "123.45"
