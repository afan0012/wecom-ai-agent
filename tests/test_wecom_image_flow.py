import asyncio

from app import main
from app.config import settings
from app.knowledge import Answer


def test_standalone_image_is_answered_without_writing_it_to_disk(monkeypatch) -> None:
    sent: list[tuple[str, str, str]] = []

    async def fake_answer(question: str, customer_id: str, image_data_url: str | None = None) -> Answer:
        assert image_data_url == "data:image/png;base64,AA=="
        return Answer(text="我看到了图片。", score=0.9, sources=[])

    async def fake_send(customer_id: str, open_kfid: str, content: str) -> None:
        sent.append((customer_id, open_kfid, content))

    async def case() -> None:
        old_delay = settings.image_followup_seconds
        settings.image_followup_seconds = 0
        try:
            pending = main._store_pending_image("customer", "kfid", "data:image/png;base64,AA==")
            pending.task = asyncio.create_task(main._reply_to_standalone_image("customer", "kfid", pending))
            await pending.task
        finally:
            settings.image_followup_seconds = old_delay
            main._pending_images.clear()

    monkeypatch.setattr(main, "answer_question", fake_answer)
    monkeypatch.setattr(main.wecom_kf_client, "send_text", fake_send)
    asyncio.run(case())
    assert sent == [("customer", "kfid", "我看到了图片。")]
