"""Cấu hình qua biến môi trường (xem .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="INGEST_", extra="ignore")

    # Temporal
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    ingest_tq: str = "ingest-tq"
    convert_tq: str = "convert-tq"
    index_tq: str = "index-tq"

    # Metadata DB
    database_url: str = "postgresql+psycopg://ingest:ingest@localhost:5433/ingest"

    # Object storage (S3 / MinIO)
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "ingest"
    s3_region: str = "us-east-1"

    # Vector DB
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"

    # Embedding (API tương thích OpenAI)
    embed_base_url: str = "http://localhost:11434/v1"
    embed_api_key: str = "none"
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    embed_max_tokens: int = 8192

    # Chunking
    chunk_tokens: int = 512
    chunk_overlap: int = 64
    chunk_batch_size: int = 100

    # OCR
    ocr_pages_per_batch: int = 10
    ocr_lang: str = "vie+eng"
    min_ocr_confidence: float = 0.6
    review_enabled: bool = False
    prefer_docling: bool = False

    # Mọi ảnh (ảnh trong docx/xlsx, trang PDF scan, file ảnh). Tên giữ "docx_" cho tương thích.
    # auto: OCR trước; chart, sơ đồ, bảng chụp (xem parsers/image_kind.py) mới gọi Vision LLM
    docx_image_mode: Literal["auto", "ocr", "vision"] = "auto"
    docx_min_image_bytes: int = 2048  # nhỏ hơn thường là icon, gạch đầu dòng

    # xlsx: thêm bảng công thức nguyên văn (=SUM(A1:A10)...) kèm giá trị đã tính
    xlsx_formulas: bool = True

    # Vision LLM (API tương thích OpenAI: Gemini, GPT-4o, Qwen2-VL qua vLLM/Ollama).
    # Để trống vision_model là tắt.
    vision_base_url: str = "http://localhost:11434/v1"
    vision_api_key: str = "none"
    vision_model: str = ""
    vision_timeout: float = 120

    # Worker
    convert_max_concurrent_activities: int = 4
    index_max_activities_per_second: float = 5.0

    # API
    max_upload_bytes: int = 100 * 1024 * 1024
    api_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
