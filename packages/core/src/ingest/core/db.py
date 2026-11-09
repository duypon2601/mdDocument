"""Metadata DB: danh mục tài liệu và trạng thái nghiệp vụ (SQLAlchemy)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

STATUSES = (
    "RECEIVED",
    "CONVERTING",
    "NEEDS_REVIEW",
    "CONVERTED",
    "INDEXING",
    "INDEXED",
    "FAILED",
    "CANCELLED",
)


_SCHEMA_LOCK_KEY = 726_100_001


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(128), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    index_version: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


@dataclass
class DocumentRecord:
    doc_id: str
    file_name: str
    mime: str
    size: int
    status: str
    error_code: str | None
    chunk_count: int
    index_version: int
    embedding_model: str
    created_at: datetime
    updated_at: datetime


def _rec(d: Document) -> DocumentRecord:
    return DocumentRecord(
        d.doc_id, d.file_name, d.mime, d.size, d.status, d.error_code, d.chunk_count,
        d.index_version, d.embedding_model, d.created_at, d.updated_at,
    )  # fmt: skip


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite") and ":memory:" in url:
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


class DocumentRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sm = sessionmaker(engine, expire_on_commit=False)

    def create_schema(self) -> None:
        """An toàn khi nhiều tiến trình khởi động cùng lúc (API và worker)."""
        if self.engine.dialect.name != "postgresql":
            Base.metadata.create_all(self.engine)
            return
        # Khóa advisory theo phiên giữ trong lúc create_all; CREATE TYPE/TABLE song song
        # trên Postgres có thể ném UniqueViolation.
        with self.engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _SCHEMA_LOCK_KEY})
            try:
                Base.metadata.create_all(conn)
                conn.commit()
            finally:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SCHEMA_LOCK_KEY})
                conn.commit()

    def get_or_create(
        self, doc_id: str, file_name: str, mime: str = "", size: int = 0
    ) -> tuple[DocumentRecord, bool]:
        """Trả (record, created). Gọi lại cùng doc_id không tạo bản trùng."""
        with self._sm.begin() as s:
            d = s.get(Document, doc_id)
            if d is not None:
                return _rec(d), False
            d = Document(doc_id=doc_id, file_name=file_name, mime=mime, size=size)
            s.add(d)
            s.flush()
            return _rec(d), True

    def get(self, doc_id: str) -> DocumentRecord | None:
        with self._sm() as s:
            d = s.get(Document, doc_id)
            return _rec(d) if d else None

    def set_status(
        self,
        doc_id: str,
        status: str,
        error_code: str | None = None,
        chunk_count: int | None = None,
        index_version: int | None = None,
        embedding_model: str | None = None,
    ) -> None:
        """Ghi giá trị tuyệt đối nên chạy lại không sai. error_code=None xóa mã lỗi cũ."""
        if status not in STATUSES:
            raise ValueError(f"status không hợp lệ: {status}")
        with self._sm.begin() as s:
            d = s.get(Document, doc_id)
            if d is None:
                raise LookupError(f"không có document {doc_id}")
            d.status = status
            d.error_code = error_code
            if chunk_count is not None:
                d.chunk_count = chunk_count
            if index_version is not None:
                d.index_version = index_version
            if embedding_model is not None:
                d.embedding_model = embedding_model
            d.updated_at = _now()

    def list(
        self,
        status: str | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DocumentRecord], int]:
        with self._sm() as s:
            stmt = select(Document)
            cnt = select(func.count()).select_from(Document)
            if status:
                stmt = stmt.where(Document.status == status)
                cnt = cnt.where(Document.status == status)
            if q:
                like = f"%{q}%"
                stmt = stmt.where(Document.file_name.ilike(like))
                cnt = cnt.where(Document.file_name.ilike(like))
            stmt = stmt.order_by(Document.created_at.desc(), Document.doc_id).limit(limit)
            stmt = stmt.offset(offset)
            return [_rec(d) for d in s.scalars(stmt)], s.scalar(cnt) or 0


def session_factory(url: str) -> DocumentRepository:
    repo = DocumentRepository(make_engine(url))
    repo.create_schema()
    return repo


__all__ = ["Document", "DocumentRecord", "DocumentRepository", "Session", "STATUSES"]
