# Piece và split_markdown_tables adapted from rag-starter (MIT, Copyright (c) 2026 Anas Ahmad)
"""Định dạng Markdown trung gian mà Conversion Worker ghi ra và Indexing Worker đọc vào.

Marker trang `<!-- page: N -->`, đơn vị nội dung Piece và cách tách bảng khỏi văn xuôi.
"""

import re
from dataclasses import dataclass, field
from hashlib import sha256

PAGE_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")


def page_marker(page: int) -> str:
    return f"<!-- page: {page} -->"


@dataclass
class Piece:
    """Một đơn vị nội dung đã trích, trước khi chunk."""

    content: str
    content_type: str = "TEXT"  # TEXT | TABLE | IMAGE
    page: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


def split_markdown_tables(text: str) -> list[Piece]:
    """Tách bảng Markdown khỏi văn xuôi để mỗi phần có đúng content_type."""
    pieces: list[Piece] = []
    buffer: list[str] = []
    table: list[str] = []

    def flush(lines: list[str], content_type: str) -> None:
        content = "\n".join(lines).strip()
        if content:
            pieces.append(Piece(content=content, content_type=content_type))

    for line in text.splitlines():
        is_table_row = line.lstrip().startswith("|") and line.rstrip().endswith("|")
        if is_table_row:
            if buffer:
                flush(buffer, "TEXT")
                buffer = []
            table.append(line)
        else:
            if table:
                flush(table, "TABLE")
                table = []
            buffer.append(line)
    flush(table, "TABLE")
    flush(buffer, "TEXT")
    return pieces
