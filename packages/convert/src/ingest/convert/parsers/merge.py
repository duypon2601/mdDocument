"""Gộp Markdown theo thứ tự trang, bỏ header/footer lặp lại, thêm front-matter."""

import re
from collections import Counter

import frontmatter

from ingest.core.markdown import PAGE_RE, page_marker  # noqa: F401  (re-export)


def split_pages(md: str) -> dict[int, str]:
    """Tách theo marker. Phần không có marker (office, html) gom vào trang 0."""
    parts = PAGE_RE.split(md)
    pages: dict[int, str] = {}
    if parts[0].strip():
        pages[0] = parts[0].strip()
    for i in range(1, len(parts), 2):
        txt = parts[i + 1].strip()
        if txt:
            pages[int(parts[i])] = (pages.get(int(parts[i])) or "") + txt
    return pages


def _norm(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def drop_repeated_edges(pages: dict[int, str], edge: int = 3, ratio: float = 0.5) -> dict[int, str]:
    """Dòng ngắn lặp ở đầu/cuối >= ratio số trang (từ 3 trang) là header/footer."""
    real = {p: t for p, t in pages.items() if p > 0}
    if len(real) < 3:
        return pages
    counts: Counter[str] = Counter()
    for t in real.values():
        lines = [ln for ln in t.splitlines() if ln.strip()]
        edges = set(lines[:edge] + lines[-edge:])
        counts.update(_norm(ln) for ln in edges if len(ln.strip()) <= 100)
    bad = {k for k, c in counts.items() if c >= max(3, ratio * len(real))}
    if not bad:
        return pages
    out = dict(pages)
    for p, t in real.items():
        lines = t.splitlines()
        keep = [
            ln
            for idx, ln in enumerate(lines)
            if not (_norm(ln) in bad and (idx < edge * 2 or idx >= len(lines) - edge * 2))
        ]
        out[p] = "\n".join(keep).strip()
    return out


def merge_markdown(
    parts: list[str], file_name: str, doc_id: str, page_count: int = 0
) -> tuple[str, int]:
    """Trả (markdown cuối, số ký tự nội dung). Rỗng thì số ký tự là 0."""
    pages: dict[int, str] = {}
    for part in parts:
        for p, t in split_pages(part).items():
            pages[p] = f"{pages[p]}\n\n{t}" if p in pages else t
    pages = drop_repeated_edges(pages)
    body_parts = []
    for p in sorted(pages):
        if not pages[p].strip():
            continue
        body_parts.append(f"{page_marker(p)}\n\n{pages[p]}" if p > 0 else pages[p])
    body = "\n\n".join(body_parts).strip()
    chars = len("".join(PAGE_RE.sub("", body).split()))
    if chars == 0:
        return "", 0
    post = frontmatter.Post(
        body, doc_id=doc_id, title=file_name, pages=page_count or len([p for p in pages if p > 0])
    )
    return frontmatter.dumps(post) + "\n", chars
