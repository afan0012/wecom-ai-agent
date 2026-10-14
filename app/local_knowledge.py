"""Small, auditable Markdown knowledge-base retrieval.

This intentionally avoids a vector database for the first deployment. Only
Markdown files under ``knowledge/approved`` are eligible for retrieval. New
material is first imported to ``knowledge/drafts`` and only moved here after a
human review. The index is cached in memory and refreshes when a file changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.config import settings


@dataclass(frozen=True)
class KnowledgeMatch:
    source: str
    content: str
    score: float


_INDEX_CACHE: dict[Path, tuple[tuple[tuple[str, int, int], ...], list[tuple[str, str]]]] = {}


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


def _strip_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    """Read simple YAML-like frontmatter without adding a parser dependency."""
    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}, markdown
    metadata: dict[str, str] = {}
    for line in markdown[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip().strip('"\'').lower()
    return metadata, markdown[end + 5 :]


def _snapshot(paths: Iterable[Path], root: Path) -> tuple[tuple[str, int, int], ...]:
    result: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append((str(path.relative_to(root)), stat.st_mtime_ns, stat.st_size))
    return tuple(result)


def _approved_chunks(root: Path) -> list[tuple[str, str]]:
    paths = sorted(root.rglob("*.md")) if root.is_dir() else []
    snapshot = _snapshot(paths, root)
    cached = _INDEX_CACHE.get(root)
    if cached and cached[0] == snapshot:
        return cached[1]

    chunks: list[tuple[str, str]] = []
    for path in paths:
        try:
            markdown = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata, body = _strip_frontmatter(markdown)
        # Private and draft material must never be surfaced merely because it
        # was copied into the approved tree by mistake.
        if metadata.get("audience", "public") not in {"public", "external"}:
            continue
        source = str(path.relative_to(root))
        chunks.extend((source, chunk) for chunk in _chunks(body))
    _INDEX_CACHE[root] = (snapshot, chunks)
    return chunks


def search_approved_knowledge(question: str) -> list[KnowledgeMatch]:
    root = Path(settings.knowledge_base_dir)
    if not root.is_dir():
        return []

    terms = _query_terms(question)
    if not terms:
        return []

    matches: list[KnowledgeMatch] = []
    for source, chunk in _approved_chunks(root):
        chunk_terms = _query_terms(chunk)
        overlap = terms & chunk_terms
        if not overlap:
            continue
        # Favour coverage of the user's question, then reward exact phrase
        # matches. It remains inspectable and has no embedding service cost.
        coverage = len(overlap) / len(terms)
        density = len(overlap) / max(len(chunk_terms), 1)
        phrase_bonus = 0.35 if question.strip().lower() in chunk.lower() else 0.0
        score = coverage * 10 + density + phrase_bonus
        matches.append(KnowledgeMatch(source, chunk, score))

    return sorted(matches, key=lambda item: item.score, reverse=True)


def format_knowledge_context(question: str) -> tuple[str, list[str]]:
    remaining = settings.knowledge_max_chars
    excerpts: list[str] = []
    sources: list[str] = []
    for match in search_approved_knowledge(question)[: settings.knowledge_max_chunks]:
        if remaining <= 0:
            break
        excerpt = match.content[:remaining]
        excerpts.append(f"[来源：{match.source}]\n{excerpt}")
        sources.append(match.source)
        remaining -= len(excerpt)
    return "\n\n".join(excerpts), list(dict.fromkeys(sources))
