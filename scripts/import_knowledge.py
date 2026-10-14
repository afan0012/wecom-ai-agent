"""Copy Markdown and text files into the non-public knowledge review queue.

Example:
    python scripts/import_knowledge.py "D:\\My Obsidian Vault"

The script deliberately imports into ``knowledge/drafts`` only. A person must
review each file and explicitly move it into ``knowledge/approved`` before the
customer-service bot can use it.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ALLOWED_SUFFIXES = {".md", ".txt"}


def _files(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.lower() in ALLOWED_SUFFIXES else []
    return [path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES]


def _safe_relative(source: Path, path: Path) -> Path:
    return path.name if source.is_file() else path.relative_to(source)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Markdown/TXT files into the review-only knowledge queue.")
    parser.add_argument("source", type=Path, help="A Markdown/TXT file or a folder such as an Obsidian vault")
    parser.add_argument("--target", type=Path, default=Path("knowledge/drafts"), help="Review queue folder")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    if not source.exists():
        parser.error(f"Source does not exist: {source}")
    candidates = _files(source)
    args.target.mkdir(parents=True, exist_ok=True)

    copied = 0
    for path in candidates:
        destination = args.target / _safe_relative(source, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1

    print(f"Imported {copied} file(s) into {args.target}. Review them before moving any file to knowledge/approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
