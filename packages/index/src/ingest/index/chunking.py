# Adapted from rag-starter (MIT, Copyright (c) 2026 Anas Ahmad)
"""Chunk theo cấu trúc (heading) trước, theo độ dài token sau (mặc định 512/64).

Markdown cuối có marker `<!-- page: N -->`. Tách theo marker thành Piece (TEXT/TABLE),
gộp các Piece nhỏ cùng trang, rồi chia theo heading. Bảng không bị cắt.
Giữ từ rag-starter: _chunk_with_structure, _heading_path, _merge_fragmented_pieces,
_merge_undersized_sections. Khác: đo độ dài bằng token, trả Chunk với heading_path,
page_start/page_end, content_hash thay vì langchain Document.
"""

import hashlib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import frontmatter
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from ingest.core.markdown import PAGE_RE, Piece, split_markdown_tables

_MARKDOWN_HEADERS = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]
_RECURSIVE_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


@dataclass
class ChunkerSettings:
    max_size: int = 512  # token
    overlap: int = 64


@dataclass
class Chunk:
    chunk_index: int
    text: str
    heading_path: str
    page_start: int
    page_end: int
    content_hash: str


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # không tải được bảng mã (offline): ước lượng theo ký tự
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is not None:
        return len(enc.encode(text, disallowed_special=()))
    return math.ceil(len(text) / 4)


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _recursive(settings: ChunkerSettings) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.max_size,
        chunk_overlap=settings.overlap,
        length_function=count_tokens,
        separators=list(_RECURSIVE_SEPARATORS),
    )


def _looks_like_markdown(text: str) -> bool:
    return any(line.strip().startswith("#") for line in text.splitlines()[:30])


def _heading_path(metadata: dict[str, Any]) -> str:
    parts = [metadata[key] for key in ("Header 1", "Header 2", "Header 3") if key in metadata]
    return " > ".join(parts) if parts else ""


_HEADING_LIKE = re.compile(r"^(\d+[.)]\s+\S|#{1,6}\s+\S)")


def _looks_like_bare_heading(text: str) -> bool:
    """True cho nhãn ngắn không dấu câu như "8. Model Providers" hoặc "## Tiêu đề"."""
    text = text.strip()
    if not text or len(text) >= 80 or text[-1] in ".!?:":
        return False
    return bool(_HEADING_LIKE.match(text))


def _merge_fragmented_pieces(pieces: list[Piece], settings: ChunkerSettings) -> list[Piece]:
    """Gộp các Piece TEXT nhỏ liên tiếp cùng trang để heading không đứng riêng một chunk.

    TABLE và IMAGE không bao giờ gộp. Heading trần ngay trước bảng được dính vào bảng.
    """
    merged: list[Piece] = []
    buffer: list[Piece] = []
    buffer_len = 0

    def flush() -> None:
        nonlocal buffer, buffer_len
        if buffer:
            merged.append(
                Piece(
                    content="\n\n".join(p.content for p in buffer),
                    content_type="TEXT",
                    page=buffer[0].page,
                    metadata=buffer[0].metadata,
                )
            )
        buffer = []
        buffer_len = 0

    for piece in pieces:
        if piece.content_type != "TEXT":
            if buffer and len(buffer) == 1 and _looks_like_bare_heading(buffer[0].content):
                heading = buffer[0]
                piece = Piece(
                    content=f"{heading.content}\n\n{piece.content}",
                    content_type=piece.content_type,
                    page=piece.page,
                    metadata=piece.metadata,
                )
                buffer = []
                buffer_len = 0
            else:
                flush()
            merged.append(piece)
            continue

        joins_buffer = buffer and buffer[-1].page == piece.page
        projected = buffer_len + count_tokens(piece.content) + 1
        if joins_buffer and projected <= settings.max_size:
            buffer.append(piece)
            buffer_len = projected
        else:
            flush()
            buffer = [piece]
            buffer_len = count_tokens(piece.content)

    flush()
    return merged


# Section chỉ gồm dòng heading, không có thân
_HEADING_ONLY_SECTION = re.compile(r"^(#{1,6}\s+.+\n?)+$")


def _merge_undersized_sections(
    sections: list[tuple[str, dict]], settings: ChunkerSettings
) -> list[tuple[str, dict]]:
    """Gộp section chỉ có heading vào section liền trước (hoặc liền sau nếu là đầu tiên)."""
    if not sections:
        return sections

    merged: list[tuple[str, dict]] = []
    for text, extra in sections:
        if (
            merged
            and _HEADING_ONLY_SECTION.match(text)
            and count_tokens(merged[-1][0]) + count_tokens(text) + 1 <= settings.max_size
        ):
            prev_text, prev_extra = merged[-1]
            merged[-1] = (f"{prev_text}\n\n{text}", prev_extra)
        else:
            merged.append((text, extra))

    if (
        len(merged) > 1
        and _HEADING_ONLY_SECTION.match(merged[0][0])
        and count_tokens(merged[0][0]) + count_tokens(merged[1][0]) + 1 <= settings.max_size
    ):
        first_text, _ = merged[0]
        next_text, next_extra = merged[1]
        merged[1] = (f"{first_text}\n\n{next_text}", next_extra)
        merged = merged[1:]

    return merged


def _chunk_with_structure(content: str, settings: ChunkerSettings) -> list[tuple[str, dict]]:
    if _looks_like_markdown(content):
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=list(_MARKDOWN_HEADERS), strip_headers=False
        )
        result: list[tuple[str, dict]] = []
        for doc in md_splitter.split_text(content):
            text = doc.page_content.strip()
            if not text:
                continue
            path = _heading_path(doc.metadata)
            extra = {"section_path": path} if path else {}
            if count_tokens(text) > settings.max_size:
                for sub in _recursive(settings).split_text(text):
                    result.append((sub, extra))
            else:
                result.append((text, extra))
        return _merge_undersized_sections(result, settings)

    return [(text, {}) for text in _recursive(settings).split_text(content)]


def _pieces_from_markdown(body: str) -> list[Piece]:
    """Tách theo marker trang, rồi tách bảng khỏi văn xuôi. Trang 0 (không marker) thành 1."""
    parts = PAGE_RE.split(body)
    segments: list[tuple[int, str]] = []
    if parts[0].strip():
        segments.append((1, parts[0]))
    for i in range(1, len(parts), 2):
        segments.append((int(parts[i]), parts[i + 1]))
    pieces: list[Piece] = []
    for page, text in segments:
        for p in split_markdown_tables(text.strip()):
            p.page = str(page)
            pieces.append(p)
    return pieces


def chunk_markdown_text(md: str, size: int = 512, overlap: int = 64) -> list[Chunk]:
    settings = ChunkerSettings(size, overlap)
    body = frontmatter.loads(md).content
    out: list[Chunk] = []
    carried_path = ""  # heading của trang trước, cho đoạn tiếp nối không có heading
    for piece in _merge_fragmented_pieces(_pieces_from_markdown(body), settings):
        if piece.content_type == "TABLE":
            if not any(c.isalnum() for c in piece.content):
                continue
            chunks: list[tuple[str, dict]] = [(piece.content, {})]
        else:
            chunks = _chunk_with_structure(piece.content, settings)
        page = int(piece.page or 1)
        for text, extra in chunks:
            text = text.strip()
            if not text:
                continue
            path = extra.get("section_path") or carried_path
            if extra.get("section_path"):
                carried_path = path
            out.append(Chunk(len(out), text, path, page, page, content_hash(text)))
    return out
