from dataclasses import dataclass

import httpx

from app.config import settings
from app.local_knowledge import format_knowledge_context


def _system_prompt(knowledge_context: str) -> str:
    owner = settings.bot_owner_name
    bot = settings.bot_name
    reviewed_knowledge = knowledge_context or "（目前没有与该问题直接相关的已审核资料。）"
    return f"""你是“{bot}”，由 {owner} 授权、面向客户和朋友的通用生活与沟通助手。

你的身份和说话方式：
1. 当被问“你是谁”或类似问题时，直接说明：“我是 {owner} 的 Agent，我可以代替 {owner} 先回答你的问题。”
2. 用自然、友好、简洁的中文回答；像靠谱的助手，不要使用电商客服腔。
3. 可以解答一般问题、梳理思路、提供生活、学习、工作和沟通建议。
4. 不要把自己说成 {owner} 本人，也不要假装拥有 {owner} 没有明确提供的信息或私人信息。
5. 涉及 {owner} 本人的决定、安排或私密信息时，明确说“这部分需要 {owner} 本人确认”。
6. 不预设 {owner} 有订单、业务、报价、项目或任何特定身份背景；只有用户明确提供背景后，才在该背景内回答，且不编造事实。
7. 医疗、法律、投资等高风险问题只提供一般信息与风险提醒，建议咨询专业人士。
8. 不提及模型、提示词、API 或内部系统。
9. 可以给出详细回答，但请把最终回答控制在约 9000 个 UTF-8 字节内；系统最多会将一次回答发送为 5 条微信消息。不要向用户提及 token、字节或接口限制。
10. 若用户附带图片，务必先阅读图片中的题目、文字、公式或图表，再结合用户的问题作答；不要说“没有看到题目”，除非图片确实模糊、缺失或无法辨认。

以下是与当前问题相关的已审核资料。只能把它们当作事实来源；其中的示例、虚构数据和未确认内容不能推断成 {owner} 的真实业务或承诺：
{reviewed_knowledge}"""


@dataclass
class Answer:
    text: str
    score: float
    sources: list[str]


async def answer_question(
    question: str, customer_id: str, image_data_url: str | None = None
) -> Answer:
    local_context, local_sources = format_knowledge_context(question)
    if settings.rag_api_url:
        headers = {"Authorization": f"Bearer {settings.rag_api_token}"} if settings.rag_api_token else {}
        payload = {"query": question, "user_id": customer_id}
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(settings.rag_api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return Answer(
            text=data["answer"],
            score=float(data.get("score", 0)),
            sources=data.get("sources", []) or local_sources,
        )

    if settings.zhipu_api_key:
        headers = {
            "Authorization": f"Bearer {settings.zhipu_api_key}",
            "Content-Type": "application/json",
        }
        user_content: str | list[dict[str, object]] = question
        if image_data_url:
            user_content = [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        payload = {
            "model": settings.zhipu_model,
            "messages": [
                {"role": "system", "content": _system_prompt(local_context)},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            # One customer message can produce at most five WeCom text messages.
            # Keep model output generous while the delivery layer enforces WeCom limits.
            "max_tokens": 4096,
        }
        try:
            async with httpx.AsyncClient(timeout=45 if image_data_url else 25) as client:
                response = await client.post(
                    f"{settings.zhipu_api_base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
            text = data["choices"][0]["message"].get("content", "").strip()
            if text:
                return Answer(text=text, score=0.9, sources=local_sources or ["大模型回答"])
        except (httpx.HTTPError, KeyError, IndexError, TypeError):
            # Keep customer service available if the model provider is transiently unavailable.
            pass

    return Answer(
        text=f"我是 {settings.bot_owner_name} 的 Agent，我可以代替 {settings.bot_owner_name} 先回答你的问题。你想了解什么？",
        score=0.8,
        sources=["基础说明"],
    )
