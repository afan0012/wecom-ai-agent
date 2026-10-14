import logging
import time
import uuid
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# httpx at INFO logs complete request URLs.  WeCom access tokens and the
# application secret travel in query parameters, so keep this dependency quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

_MAX_WECHAT_TEXT_BYTES = 2048
_MAX_WECHAT_MESSAGES_PER_REPLY = 5


def _split_wechat_text(content: str) -> list[str]:
    """Split text on UTF-8 boundaries for WeCom's 2048-byte text limit."""
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for character in content:
        character_size = len(character.encode("utf-8"))
        if current and current_size + character_size > _MAX_WECHAT_TEXT_BYTES:
            chunks.append("".join(current))
            current = []
            current_size = 0
        current.append(character)
        current_size += character_size
    if current:
        chunks.append("".join(current))

    if len(chunks) <= _MAX_WECHAT_MESSAGES_PER_REPLY:
        return chunks or ["…"]

    # WeCom will reject a sixth message for the same customer action.  Preserve
    # a clear completion marker without violating the single-message byte cap.
    suffix = "\n\n（内容较长，本次回复已到微信客服的发送上限。）"
    final_size = len(suffix.encode("utf-8"))
    last = chunks[_MAX_WECHAT_MESSAGES_PER_REPLY - 1]
    while last and len(last.encode("utf-8")) + final_size > _MAX_WECHAT_TEXT_BYTES:
        last = last[:-1]
    return chunks[: _MAX_WECHAT_MESSAGES_PER_REPLY - 1] + [last + suffix]


class WeComKfClient:
    """Small async client for the WeCom WeChat Customer Service APIs."""

    def __init__(self) -> None:
        self._access_token = ""
        self._access_token_expires_at = 0.0

    async def _get_access_token(self) -> str:
        if not settings.wecom_corp_id or not settings.wecom_kf_secret:
            raise RuntimeError("微信客服 CorpID 或 Secret 尚未配置")
        if self._access_token and time.time() < self._access_token_expires_at:
            return self._access_token

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{settings.wecom_api_base}/gettoken",
                params={"corpid": settings.wecom_corp_id, "corpsecret": settings.wecom_kf_secret},
            )
            response.raise_for_status()
            data = response.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"获取微信客服 access_token 失败：{data}")
        self._access_token = data["access_token"]
        self._access_token_expires_at = time.time() + max(int(data.get("expires_in", 7200)) - 300, 60)
        return self._access_token

    async def sync_messages(
        self, callback_token: str, open_kfid: str, cursor: str = ""
    ) -> tuple[list[dict[str, Any]], str]:
        access_token = await self._get_access_token()
        next_cursor = cursor
        result: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15) as client:
            while True:
                response = await client.post(
                    f"{settings.wecom_api_base}/kf/sync_msg",
                    params={"access_token": access_token},
                    json={"token": callback_token, "open_kfid": open_kfid, "cursor": next_cursor, "limit": 1000},
                )
                response.raise_for_status()
                data = response.json()
                if data.get("errcode", 0) != 0:
                    raise RuntimeError(f"读取微信客服消息失败：{data}")
                result.extend(data.get("msg_list", []))
                next_cursor = data.get("next_cursor", next_cursor)
                if not data.get("has_more"):
                    return result, next_cursor
                if not next_cursor:
                    return result, next_cursor

    async def send_text(self, customer_id: str, open_kfid: str, content: str) -> None:
        access_token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=15) as client:
            for part in _split_wechat_text(content):
                payload = {
                    "touser": customer_id,
                    "open_kfid": open_kfid,
                    # WeCom accepts at most 32 characters for msgid.
                    "msgid": uuid.uuid4().hex,
                    "msgtype": "text",
                    "text": {"content": part},
                }
                response = await client.post(
                    f"{settings.wecom_api_base}/kf/send_msg",
                    params={"access_token": access_token},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("errcode", 0) != 0:
                    raise RuntimeError(f"发送微信客服消息失败：{data}")

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download a WeCom temporary media object without writing it to disk."""
        access_token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{settings.wecom_api_base}/media/get",
                params={"access_token": access_token, "media_id": media_id},
            )
            response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            raise RuntimeError(f"下载的微信客服素材不是图片：{content_type or 'unknown'}")
        return response.content, content_type


wecom_kf_client = WeComKfClient()
