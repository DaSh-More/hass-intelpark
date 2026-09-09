"""HTTP-клиент REST API Intelpark («Дворецкий»)."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import aiohttp

from .const import BASE_URL, CLIENT, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_AUTH_MARKERS = ("hash", "auth", "авториз", "unauthorized")


def normalize_phone(raw: str) -> str:
    """Привести телефон к формату API: '7' + 10 цифр, без '+'."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "7" + digits[1:]
    if len(digits) == 10:
        return "7" + digits
    raise ValueError(f"Не удалось разобрать номер телефона: {raw!r}")


@dataclass(slots=True)
class Camera:
    cam_id: str
    name: str
    object_name: str
    snapshot: str
    stream: str
    stream_token: str
    stream_token_valid_till: int

    @classmethod
    def from_json(cls, d: dict) -> "Camera":
        try:
            return cls(
                cam_id=str(d["camId"]),
                name=d.get("camName") or str(d["camId"]),
                object_name=d.get("objectName") or "",
                snapshot=d.get("snapshot") or "",
                stream=d.get("stream") or "",
                stream_token=d.get("streamToken") or "",
                stream_token_valid_till=int(d.get("streamTokenValidTill") or 0),
            )
        except (KeyError, ValueError, TypeError) as err:
            raise IntelparkError(f"Некорректные данные камеры: {err}") from err

    def stream_url(self) -> str:
        return f"{self.stream}/index.m3u8?token={self.stream_token}"

    def archive_mp4_url(self, start: str, duration: str) -> str:
        return f"{self.stream}/archive-{start}-{duration}.mp4?token={self.stream_token}"


@dataclass(slots=True)
class Gate:
    gid: str
    name: str
    object_id: int
    object_name: str
    live_url: str
    live_cam: str = ""
    snapshot_image: str = ""

    @classmethod
    def from_json(cls, d: dict, object_id: int, object_name: str) -> "Gate":
        try:
            return cls(
                gid=str(d["gid"]),
                name=d.get("name") or f"Ворота {d['gid']}",
                object_id=object_id,
                object_name=object_name,
                live_url=d.get("liveUrl") or "",
                live_cam=str(d.get("liveCam") or ""),
                snapshot_image=d.get("snapshotImage") or "",
            )
        except (KeyError, ValueError, TypeError) as err:
            raise IntelparkError(f"Некорректные данные ворот: {err}") from err

    @property
    def gate_id_int(self) -> int:
        return int(self.gid)

    def live_stream_url(self) -> str:
        # mono.m3u8: одно качество, MPEG-TS сегменты (.ts) — их принимает HLS-демуксер
        # ffmpeg внутри Home Assistant. Дефолтный index.m3u8 отдаёт fMP4-сегменты с
        # расширением .fmp4, которого нет в allowed_extensions ffmpeg → он отклоняет их
        # («Invalid data found»), и поток в HA не открывается. (Приложение играет
        # index.m3u8 через ExoPlayer, которому расширение .fmp4 не мешает.)
        return f"{self.live_url}/mono.m3u8"


@dataclass(slots=True)
class AccountPlace:
    oid: int
    name: str
    balance: str

    @classmethod
    def from_json(cls, d: dict) -> "AccountPlace":
        try:
            # реальный ответ get_objects использует ключ "id" (строка), не "oid";
            # оставляем oid как запасной вариант на случай различий версий API.
            raw_id = d.get("id") if d.get("id") is not None else d.get("oid")
            return cls(
                oid=int(raw_id or 0),
                name=d.get("name") or "",
                balance=str(d.get("balance") if d.get("balance") is not None else ""),
            )
        except (KeyError, ValueError, TypeError) as err:
            raise IntelparkError(f"Некорректные данные объекта: {err}") from err


class IntelparkError(Exception):
    """Общая ошибка API Intelpark."""


class IntelparkConnectionError(IntelparkError):
    """Сетевая ошибка / таймаут."""


class IntelparkAuthError(IntelparkError):
    """Недействительные учётные данные (нужен reauth)."""


def _lenient_json(s: str):
    """json.loads, терпимый к неэкранированным управляющим символам в строках."""
    return json.loads(s, strict=False)


def _looks_like_auth_error(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _AUTH_MARKERS)


class IntelparkApiClient:
    """Асинхронный клиент REST API Intelpark."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        phone: str = "",
        hash_: str = "",
    ) -> None:
        self._session = session
        self.phone = phone
        self.hash = hash_

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        authed: bool = True,
    ):
        query: dict = {"client": CLIENT}
        if authed:
            query["phone"] = self.phone
            query["hash"] = self.hash
        if params:
            query.update(params)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.request(
                    method, BASE_URL + path, params=query, json=json_body
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise IntelparkConnectionError(str(err)) from err

        status = resp.status
        try:
            # strict=False: сервер иногда отдаёт неэкранированные переводы строк
            # внутри строковых значений (HTML в message, многострочные тексты
            # уведомлений) — строгий json.loads на этом падает.
            data = await resp.json(content_type=None, loads=_lenient_json)
        except (aiohttp.ClientError, ValueError):
            data = None
        finally:
            resp.release()

        if status in (401, 403):
            raise IntelparkAuthError(f"HTTP {status}")
        if isinstance(data, dict) and data.get("errors"):
            text = "; ".join(str(e) for e in data["errors"])
            if authed and _looks_like_auth_error(text):
                _LOGGER.debug("Intelpark auth-marker error on %s: %s", path, text)
                raise IntelparkAuthError(text)
            raise IntelparkError(text)
        if status >= 500:
            raise IntelparkConnectionError(f"HTTP {status}")
        if status >= 400:
            raise IntelparkError(f"HTTP {status}")
        if data is None:
            raise IntelparkConnectionError("Некорректный ответ сервера")
        return data

    async def async_send_code(self, phone: str) -> None:
        data = await self._request(
            "GET",
            "v1/old_person_v2/get_auth_code",
            params={"phone": phone},
            authed=False,
        )
        if isinstance(data, dict) and data.get("sent") is False:
            msg = data.get("successMessage") or "Не удалось отправить код"
            raise IntelparkError(msg)

    async def async_get_hash(self, phone: str, code: str) -> tuple[str, str]:
        data = await self._request(
            "GET",
            "v1/old_person_v2/get_auth_hash",
            params={"phone": phone, "code": code},
            authed=False,
        )
        if not isinstance(data, dict) or not data.get("hash"):
            raise IntelparkError("Неверный код подтверждения")
        return str(data.get("phone") or phone), str(data["hash"])

    async def async_check_auth(self) -> None:
        await self._request("GET", "v1/old_person_v2/check_auth")

    async def async_get_objects(self) -> list[AccountPlace]:
        data = await self._request("GET", "v1/old_person_v2/get_objects")
        return [AccountPlace.from_json(d) for d in (data or [])]

    async def async_get_gates(self) -> list[Gate]:
        data = await self._request("GET", "v1/old_person_v2/get_gates")
        gates: list[Gate] = []
        for obj in data or []:
            oid = int(obj.get("oid") or 0)
            oname = obj.get("name") or ""
            for g in obj.get("gates") or []:
                gates.append(Gate.from_json(g, object_id=oid, object_name=oname))
        return gates

    async def async_open_gate(self, gate_id: int) -> None:
        await self._request(
            "GET", "v1/old_person_v2/open_gate", params={"gateId": gate_id}
        )

    async def async_get_cameras(self) -> list[Camera]:
        data = await self._request("GET", "v1/old_person_v2/get_cameras")
        items = data.get("list") if isinstance(data, dict) else data
        return [Camera.from_json(d) for d in (items or [])]

    async def async_get_camera(self, cam_id: str) -> Camera:
        data = await self._request(
            "GET", "v1/old_person_v2/get_cameras", params={"camId": cam_id}
        )
        return Camera.from_json(data)

    async def async_get_passes(self) -> list[dict]:
        data = await self._request("GET", "v1/old_person_v2/pass")
        return list(data or [])

    async def async_get_notifications(self) -> list[dict]:
        data = await self._request("GET", "v1/old_person_v2/notifications")
        return list(data or [])

    async def async_add_pass(self, payload: dict) -> dict:
        return await self._request(
            "PUT", "v1/old_person_v2/pass", json_body=payload
        )

    async def async_remove_pass(self, pass_id: int) -> None:
        await self._request(
            "DELETE", "v1/old_person_v2/pass", params={"id": pass_id}
        )

    async def async_set_notification_viewed(self, notif_id: str) -> None:
        await self._request(
            "PUT",
            "v1/old_person_v2/set_notification_viewed",
            params={"id": notif_id},
        )

    async def async_remove_notification(self, notif_id: str) -> None:
        await self._request(
            "DELETE", "v1/old_person_v2/notifications", params={"id": notif_id}
        )

    async def async_download_archive(
        self, camera: Camera, start: str, duration: str
    ) -> bytes:
        url = camera.archive_mp4_url(start, duration)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT * 4):
                resp = await self._session.get(url)
                resp.raise_for_status()
                return await resp.read()
        except aiohttp.ClientResponseError as err:
            raise IntelparkConnectionError(
                f"HTTP {err.status} при загрузке медиа"
            ) from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise IntelparkConnectionError(
                f"Ошибка сети при загрузке медиа ({type(err).__name__})"
            ) from err

    async def async_fetch_snapshot(self, url: str) -> bytes:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.get(url)
                resp.raise_for_status()
                return await resp.read()
        except aiohttp.ClientResponseError as err:
            raise IntelparkConnectionError(
                f"HTTP {err.status} при загрузке медиа"
            ) from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise IntelparkConnectionError(
                f"Ошибка сети при загрузке медиа ({type(err).__name__})"
            ) from err
