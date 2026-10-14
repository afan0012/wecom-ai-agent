from pathlib import Path

from app.config import settings
from app.local_knowledge import format_knowledge_context


def test_only_approved_markdown_is_retrieved(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    drafts = tmp_path / "drafts"
    approved.mkdir()
    drafts.mkdir()
    (approved / "profile.md").write_text("# 公开资料\n小明喜欢研究 AI 工具。", encoding="utf-8")
    (drafts / "private.md").write_text("# 草稿\n小明的私人行程。", encoding="utf-8")

    old_dir = settings.knowledge_base_dir
    try:
        settings.knowledge_base_dir = str(approved)
        context, sources = format_knowledge_context("小明研究哪些 AI 工具？")
    finally:
        settings.knowledge_base_dir = old_dir

    assert "小明喜欢研究 AI 工具" in context
    assert "profile.md" in sources
    assert "私人行程" not in context


def test_non_public_frontmatter_is_not_retrieved(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / "public.md").write_text(
        "---\naudience: public\n---\n# 公开资料\n小明公开分享 AI 工具。",
        encoding="utf-8",
    )
    (approved / "private.md").write_text(
        "---\naudience: private\n---\n# 私人资料\n小明的私人行程。",
        encoding="utf-8",
    )

    old_dir = settings.knowledge_base_dir
    try:
        settings.knowledge_base_dir = str(approved)
        context, sources = format_knowledge_context("小明的资料")
    finally:
        settings.knowledge_base_dir = old_dir

    assert "公开分享 AI 工具" in context
    assert "私人行程" not in context
    assert sources == ["public.md"]
