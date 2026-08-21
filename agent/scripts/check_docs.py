"""Validate local Markdown links and heading anchors in project documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_ROOTS = (ROOT / "README.md", ROOT / "docs")
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _markdown_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files.extend(
        path
        for path in sorted((ROOT / "docs").rglob("*.md"))
        if "90-archive" not in path.parts
    )
    return [path for path in files if path.exists()]


def _anchor(value: str) -> str:
    """Approximate GitHub Markdown anchor generation for local documentation links."""
    cleaned = re.sub(r"[`*_~]", "", value).strip().lower()
    cleaned = re.sub(r"[^\w\-\u4e00-\u9fff\s]", "", cleaned)
    return re.sub(r"\s+", "-", cleaned)


def _anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    anchors: set[str] = set()
    for heading in HEADING_PATTERN.findall(text):
        base = _anchor(heading)
        index = counts.get(base, 0)
        counts[base] = index + 1
        anchors.add(base if index == 0 else f"{base}-{index}")
    return anchors


def main() -> int:
    failures: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in _markdown_files():
        text = source.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = raw_target.strip().strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            local, _, anchor = target.partition("#")
            destination = source if not local else (source.parent / local).resolve()
            if not destination.exists():
                failures.append(f"{source.relative_to(ROOT)}: missing target {raw_target}")
                continue
            if anchor and destination.suffix == ".md":
                anchors = anchor_cache.setdefault(destination, _anchors(destination))
                if anchor not in anchors:
                    failures.append(
                        f"{source.relative_to(ROOT)}: missing anchor {raw_target}"
                    )
    if failures:
        print("Documentation validation failed:", *failures, sep="\n- ")
        return 1
    print(f"Documentation validation passed ({len(_markdown_files())} Markdown files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
