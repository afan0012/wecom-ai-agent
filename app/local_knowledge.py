"""Small, auditable Markdown knowledge-base retrieval.

This intentionally avoids a vector database for the first deployment.  Only
Markdown files under ``knowledge/approved`` are eligible for retrieval.  Move
new material there only after a human review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class KnowledgeMatch:
    source: str
    content: str
    score: int


def _query_terms(text: str) -> set[str]:
    words = {word.lower() for word in re.findall(r"[A-Za-z0-9_]{2,}", text)}
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    words.update(chinese[index : index + 2] for index in range(max(len(chinese) - 1, 0)))
    return words


def _chunks(markdown: str) -> list[str]:
    """Split Markdown at headings, then cap each individual prompt excerpt."""
    parts = re.split(r"(?m)(?=^#{1,3}\s)", markdown)
    result: list[str] = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        for offset in range(0, len(stripped), 2400):
            result.append(stripped[offset : offset + 2400])
    return result


def search_approved_knowledge(question: str) -> list[KnowledgeMatch]:
    root = Path(settings.knowledge_base_dir)
    if not root.is_dir():
        return []

    terms = _query_terms(question)
    matches: list[KnowledgeMatch] = []
    for path in sorted(root.rglob("*.md")):
        try:
            markdown = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for chunk in _chunks(markdown):
            chunk_terms = _query_terms(chunk)
            score = len(terms & chunk_terms)
            if score:
                matches.append(KnowledgeMatch(path.name, chunk, score))

    return sorted(matches, key=lambda item: item.score, reverse=True)


def format_knowledge_context(question: str) -> tuple[str, list[str]]:
    remaining = settings.knowledge_max_chars
    excerpts: list[str] = []
    sources: list[str] = []
    for match in search_approved_knowledge(question):
        if remaining <= 0:
            break
        excerpt = match.content[:remaining]
        excerpts.append(f"[来源：{match.source}]\n{excerpt}")
        sources.append(match.source)
        remaining -= len(excerpt)
    return "\n\n".join(excerpts), list(dict.fromkeys(sources))
