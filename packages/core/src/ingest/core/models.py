"""Payload đi qua Temporal: nhỏ, chỉ chứa key/id/số đếm. Field mới luôn có default."""

from dataclasses import dataclass, field


@dataclass
class IngestInput:
    doc_id: str
    file_name: str
    raw_key: str
    mime: str = ""
    size: int = 0
    min_ocr_confidence: float = 0.6
    review_enabled: bool = False
    review_timeout_days: int = 7
    index_version: int = 1
    embedding_model: str = ""
    extract_media: bool = True  # False: bản cũ, không bóc ảnh/chart/công thức
    # 1: chọn OCR/VLM như trước chỉnh sửa; 2: thêm phát hiện sai dấu, gọi lại khi 429,
    # thu nhỏ ảnh trước khi gửi VLM. Giữ cả hai để so sánh output trên giao diện.
    pipeline_version: int = 2


@dataclass
class IngestResult:
    doc_id: str
    status: str = ""
    chunk_count: int = 0
    error_code: str | None = None


@dataclass
class FormatInfo:
    doc_id: str
    kind: str = ""  # pdf | docx | pptx | xlsx | html | image | text
    mime: str = ""
    page_count: int = 0
    has_text: bool = True
    ocr_page_batches: list[list[int]] = field(default_factory=list)


@dataclass
class PartResult:
    doc_id: str
    md_key: str = ""
    page_count: int = 0


@dataclass
class OcrBatch:
    doc_id: str
    pages: list[int] = field(default_factory=list)
    batch_index: int = 0
    raw_key: str = ""
    kind: str = "pdf"
    pipeline_version: int = 2


@dataclass
class OcrResult:
    doc_id: str
    batch_index: int = 0
    md_key: str = ""
    confidence: float = 1.0


@dataclass
class FinalizeInput:
    doc_id: str
    file_name: str = ""
    ocr_batches: list[int] = field(default_factory=list)
    page_count: int = 0


@dataclass
class FinalizeResult:
    doc_id: str
    md_key: str = ""
    char_count: int = 0


@dataclass
class ChunkInput:
    doc_id: str
    file_name: str = ""
    index_version: int = 1
    chunk_tokens: int = 512
    chunk_overlap: int = 64
    batch_size: int = 100


@dataclass
class ChunkResult:
    doc_id: str
    index_version: int = 1
    batch_count: int = 0
    chunk_count: int = 0


@dataclass
class EmbedBatch:
    doc_id: str
    index_version: int = 1
    batch_index: int = 0


@dataclass
class EmbedResult:
    doc_id: str
    batch_index: int = 0
    upserted: int = 0


@dataclass
class CleanupInput:
    doc_id: str
    index_version: int = 1


@dataclass
class CleanupResult:
    doc_id: str
    deleted: int = 0


@dataclass
class StatusUpdate:
    doc_id: str
    status: str = ""
    error_code: str | None = None
    chunk_count: int | None = None
    index_version: int | None = None
    embedding_model: str | None = None


@dataclass
class ReindexInput:
    doc_id: str
    file_name: str = ""
    index_version: int = 2
    chunk_tokens: int = 512
    chunk_overlap: int = 64
    batch_size: int = 100
    embedding_model: str = ""


@dataclass
class StatsInput:
    doc_id: str


@dataclass
class StatsResult:
    doc_id: str
    words: int = 0
    headings: int = 0
    tables: int = 0
