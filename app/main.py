import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from xml.etree.ElementTree import Element, ParseError

from defusedxml.ElementTree import fromstring as defused_fromstring
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.config import settings
from app.knowledge import answer_question
from app.wecom_crypto import WeComCrypto, WeComCryptoError
from app.wecom_kf import wecom_kf_client
from app.wecom_state import WeComState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="企业微信客服 AI Agent", version="0.2.0")
wecom_state = WeComState(settings.wecom_state_db)
_sync_locks: dict[str, asyncio.Lock] = {}


@dataclass
class PendingImage:
    expires_at: float
    data_url: str
    task: asyncio.Task[None] | None = None


_pending_images: dict[tuple[str, str], PendingImage] = {}
_IMAGE_TTL_SECONDS = 10 * 60


class DemoQuestion(BaseModel):
    question: str
    customer_id: str = "demo-customer"


def _crypto() -> WeComCrypto:
    return WeComCrypto(settings.wecom_token, settings.wecom_encoding_aes_key, settings.wecom_corp_id)


def _element_text(root: Element, name: str) -> str:
    return root.findtext(name, default="")


def _sync_lock(open_kfid: str) -> asyncio.Lock:
    """Serialize sync_msg calls per customer-service account."""
    return _sync_locks.setdefault(open_kfid, asyncio.Lock())


def _store_pending_image(customer_id: str, open_kfid: str, data_url: str) -> PendingImage:
    key = (customer_id, open_kfid)
    old = _pending_images.pop(key, None)
    if old and old.task:
        old.task.cancel()
    pending = PendingImage(time.monotonic() + _IMAGE_TTL_SECONDS, data_url)
    _pending_images[key] = pending
    return pending


def _take_pending_image(customer_id: str, open_kfid: str) -> str | None:
    pending = _pending_images.pop((customer_id, open_kfid), None)
    if not pending:
        return None
    current_task = asyncio.current_task()
    if pending.task and pending.task is not current_task:
        pending.task.cancel()
    return pending.data_url if time.monotonic() < pending.expires_at else None


async def _send_agent_reply(customer_id: str, open_kfid: str, question: str, image_data_url: str | None = None) -> None:
    answer = await answer_question(question, customer_id, image_data_url)
    reply = answer.text if answer.score >= settings.handoff_threshold else "我暂时无法确认这个问题，已为您转人工客服处理。"
    await wecom_kf_client.send_text(customer_id, open_kfid, reply)


async def _reply_to_standalone_image(customer_id: str, open_kfid: str, pending: PendingImage) -> None:
    """Answer an image alone, but let an immediately following text explain it."""
    try:
        await asyncio.sleep(settings.image_followup_seconds)
        async with _sync_lock(open_kfid):
            key = (customer_id, open_kfid)
            if _pending_images.get(key) is not pending:
                return
            image_data_url = _take_pending_image(customer_id, open_kfid)
            if not image_data_url:
                return
            await _send_agent_reply(
                customer_id,
                open_kfid,
                "请阅读这张图片。用一两句话概括其中能确认的文字、内容或关键信息；如果用户没有说明目标，请邀请对方补充想了解什么。",
                image_data_url,
            )
            logger.info("已回复微信客服独立图片 customer=%s", customer_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("处理微信客服独立图片失败")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/demo/chat")
async def demo_chat(body: DemoQuestion) -> dict:
    answer = await answer_question(body.question, body.customer_id)
    if answer.score < settings.handoff_threshold:
        return {"reply": "我暂时无法确认这个问题，已为您转人工客服处理。", "handoff": True, "sources": []}
    return {"reply": answer.text, "handoff": False, "sources": answer.sources}


@app.get("/webhooks/wecom/kf", response_class=PlainTextResponse)
async def verify_wecom_callback(
    msg_signature: str = Query(alias="msg_signature"),
    timestamp: str = Query(),
    nonce: str = Query(),
    echostr: str = Query(),
) -> str:
    try:
        crypto = _crypto()
        if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
            raise HTTPException(status_code=403, detail="签名校验失败")
        return crypto.decrypt(echostr)
    except WeComCryptoError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _process_wecom_kf_event(callback_token: str, open_kfid: str) -> None:
    try:
        async with _sync_lock(open_kfid):
            cursor = wecom_state.get_cursor(open_kfid)
            messages, next_cursor = await wecom_kf_client.sync_messages(
                callback_token, open_kfid, cursor or ""
            )

            # The old implementation had no persisted cursor.  The first run after
            # this upgrade only establishes the checkpoint, so historical messages
            # are never answered again and cannot consume customer message quotas.
            if cursor is None:
                for item in messages:
                    if item.get("msgid"):
                        wecom_state.mark_processed(item["msgid"])
                wecom_state.set_cursor(open_kfid, next_cursor)
                logger.info("微信客服增量游标已初始化，跳过 %s 条历史消息", len(messages))
                return

            for item in messages:
                message_id = item.get("msgid", "")
                origin = item.get("origin")
                message_type = item.get("msgtype")
                already_processed = bool(message_id) and wecom_state.is_processed(message_id)
                customer_id = item.get("external_userid", "")
                item_open_kfid = item.get("open_kfid", open_kfid)

                if (
                    message_id
                    and not already_processed
                    and origin == 3
                    and message_type == "image"
                ):
                    media_id = item.get("image", {}).get("media_id", "")
                    if not customer_id or not media_id:
                        logger.info(
                            "跳过不完整微信客服图片 msgid=%s has_customer=%s has_media=%s",
                            message_id,
                            bool(customer_id),
                            bool(media_id),
                        )
                    else:
                        try:
                            image_bytes, content_type = await wecom_kf_client.download_media(media_id)
                            if len(image_bytes) > settings.vision_max_image_bytes:
                                logger.warning(
                                    "微信客服图片超过视觉模型上限 msgid=%s bytes=%s",
                                    message_id,
                                    len(image_bytes),
                                )
                            else:
                                data_url = f"data:{content_type};base64," + base64.b64encode(image_bytes).decode("ascii")
                                pending = _store_pending_image(customer_id, item_open_kfid, data_url)
                                pending.task = asyncio.create_task(
                                    _reply_to_standalone_image(customer_id, item_open_kfid, pending)
                                )
                                logger.info(
                                    "已暂存微信客服题图 msgid=%s bytes=%s",
                                    message_id,
                                    len(image_bytes),
                                )
                        except Exception:
                            logger.exception("下载微信客服图片失败 msgid=%s", message_id)
                    wecom_state.mark_processed(message_id)
                    continue

                # origin=3 means an external WeChat customer.  origin=5 is a human
                # agent message and must never trigger the AI.
                if (
                    not message_id
                    or already_processed
                    or origin != 3
                    or message_type != "text"
                ):
                    logger.info(
                        "跳过微信客服消息 msgid=%s origin=%s type=%s processed=%s",
                        message_id or "<missing>",
                        origin,
                        message_type,
                        already_processed,
                    )
                    continue
                content = item.get("text", {}).get("content", "").strip()
                if not customer_id or not content:
                    logger.info(
                        "跳过不完整微信客服文本 msgid=%s has_customer=%s content_length=%s",
                        message_id,
                        bool(customer_id),
                        len(content),
                    )
                    wecom_state.mark_processed(message_id)
                    continue
                image_data_url = _take_pending_image(customer_id, item_open_kfid)
                logger.info(
                    "处理微信客服文本 msgid=%s customer=%s content_length=%s has_image=%s",
                    message_id,
                    customer_id,
                    len(content),
                    bool(image_data_url),
                )
                try:
                    await _send_agent_reply(customer_id, item_open_kfid, content, image_data_url)
                except Exception:
                    # A message-count error must not be retried on every future
                    # callback; the customer's next message opens a fresh quota.
                    wecom_state.mark_processed(message_id)
                    raise
                wecom_state.mark_processed(message_id)
                logger.info("已发送微信客服回复 msgid=%s", message_id)
            wecom_state.set_cursor(open_kfid, next_cursor)
    except Exception:
        logger.exception("处理微信客服事件失败")


@app.post("/webhooks/wecom/kf", response_class=PlainTextResponse)
async def receive_wecom_message(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = Query(alias="msg_signature"),
    timestamp: str = Query(),
    nonce: str = Query(),
) -> str:
    body = await request.body()
    try:
        encrypted_xml = defused_fromstring(body)
        encrypted = _element_text(encrypted_xml, "Encrypt")
        crypto = _crypto()
        if not crypto.verify_signature(msg_signature, timestamp, nonce, encrypted):
            raise HTTPException(status_code=403, detail="签名校验失败")
        message_xml = crypto.decrypt(encrypted)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail="无效 XML") from exc
    except WeComCryptoError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    message = defused_fromstring(message_xml)
    if _element_text(message, "MsgType") != "event" or _element_text(message, "Event") != "kf_msg_or_event":
        return "success"
    callback_token = _element_text(message, "Token")
    open_kfid = _element_text(message, "OpenKfId")
    if not callback_token or not open_kfid:
        logger.warning("微信客服事件缺少 Token 或 OpenKfId")
        return "success"
    background_tasks.add_task(_process_wecom_kf_event, callback_token, open_kfid)
    return "success"
