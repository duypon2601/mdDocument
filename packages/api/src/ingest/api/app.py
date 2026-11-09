"""FastAPI: nhận file, kiểm tra, lưu bản gốc, khởi động workflow, trả trạng thái.

Mọi phụ thuộc (storage, repo, workflow client, settings) được tiêm qua create_app.
"""

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from ingest.api.dedup import compute_doc_id, is_legacy, profile_of
from ingest.api.validator import ValidationError, safe_name, validate_upload
from ingest.api.workflow_client import WorkflowClient, active_workflow_id
from ingest.core import keys
from ingest.core.config import Settings
from ingest.core.db import STATUSES, DocumentRecord, DocumentRepository
from ingest.core.models import IngestInput, ReindexInput
from ingest.core.storage import Storage

RUNNING_STATUSES = frozenset({"RECEIVED", "CONVERTING", "NEEDS_REVIEW", "CONVERTED", "INDEXING"})
RESTARTABLE_STATUSES = frozenset({"FAILED", "CANCELLED"})
_BATCH_RE = re.compile(r"batch-(\d+)\.jsonl$")
INDEX_HTML = Path(__file__).parent / "static" / "index.html"


def _doc_json(r: DocumentRecord) -> dict:
    d = asdict(r)
    d["created_at"] = r.created_at.isoformat()
    d["updated_at"] = r.updated_at.isoformat()
    d["extract_media"] = not is_legacy(r.doc_id)
    d["profile"] = profile_of(r.doc_id)  # legacy | v1 | v2
    return d


def create_app(
    storage: Storage,
    repo: DocumentRepository,
    wf: WorkflowClient,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Ingestion API")

    @app.exception_handler(ValidationError)
    async def _validation_handler(_, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"code": exc.code, "detail": exc.message}
        )

    async def _ingest_one(
        file_name: str, data: bytes, extract_media: bool = True, pipeline_version: int = 2
    ) -> dict:
        if pipeline_version not in (1, 2):
            raise HTTPException(422, "pipeline_version chỉ nhận 1 hoặc 2")
        vf = validate_upload(file_name, data, settings.max_upload_bytes)
        doc_id = compute_doc_id(data, extract_media, pipeline_version)
        rec, created = repo.get_or_create(doc_id, vf.file_name, vf.mime, vf.size)
        if not created and rec.status not in RESTARTABLE_STATUSES:
            return {"duplicate": True, **_doc_json(rec)}
        restarted = not created
        rkey = keys.raw_key(doc_id, vf.file_name)
        storage.put(rkey, data)  # ghi đè cùng nội dung nên chạy lại vẫn đúng
        prev = (rec.status, rec.error_code)
        if restarted:
            repo.set_status(doc_id, "RECEIVED", error_code=None)
        try:
            await wf.start_ingest(
                IngestInput(
                    doc_id=doc_id,
                    file_name=vf.file_name,
                    raw_key=rkey,
                    mime=vf.mime,
                    size=vf.size,
                    min_ocr_confidence=settings.min_ocr_confidence,
                    review_enabled=settings.review_enabled,
                    index_version=1,
                    embedding_model=settings.embed_model,
                    extract_media=extract_media,
                    pipeline_version=pipeline_version,
                )
            )
        except Exception as exc:
            # Workflow không chạy thì không để hàng kẹt ở RECEIVED
            if restarted:
                repo.set_status(doc_id, prev[0], error_code=prev[1])
            else:
                repo.set_status(doc_id, "FAILED", error_code="START_FAILED")
            if isinstance(exc, WorkflowAlreadyStartedError):
                raise HTTPException(
                    409, "Workflow của tài liệu này đang chạy hoặc đã hoàn tất"
                ) from exc
            raise
        rec = repo.get(doc_id) or rec
        return {"duplicate": False, **_doc_json(rec)}

    @app.post("/documents")
    async def upload(
        file: UploadFile = File(...),  # noqa: B008
        extract_media: bool = Form(True),  # False: bản cũ, không bóc ảnh/chart/công thức
        pipeline_version: int = Form(2),  # 1: trước chỉnh sửa, 2: sau chỉnh sửa
    ) -> JSONResponse:
        data = await file.read()
        res = await _ingest_one(safe_name(file.filename), data, extract_media, pipeline_version)
        return JSONResponse(res, status_code=200 if res["duplicate"] else 202)

    @app.post("/documents/batch")
    async def upload_batch(
        files: list[UploadFile] = File(...),  # noqa: B008
        extract_media: bool = Form(True),
        pipeline_version: int = Form(2),
    ) -> dict:
        results = []
        for f in files:
            name = safe_name(f.filename)
            try:
                res = await _ingest_one(name, await f.read(), extract_media, pipeline_version)
                results.append({"file_name": name, "ok": True, **res})
            except ValidationError as e:
                results.append(
                    {"file_name": name, "ok": False, "code": e.code, "detail": e.message}
                )
        return {"results": results}

    @app.get("/documents")
    def list_documents(
        status: str | None = None,
        q: str | None = None,
        limit: int = Query(20, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict:
        wanted = [x.strip() for x in status.split(",") if x.strip()] if status else None
        for st in wanted or []:
            if st not in STATUSES:
                raise HTTPException(422, f"status không hợp lệ: {st}")
        items, total = repo.list(status=wanted, q=q, limit=limit, offset=offset)
        return {
            "items": [_doc_json(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/stats")
    def stats() -> dict:
        total, chunks, by_status = repo.stats()
        return {"total": total, "chunks": chunks, "by_status": by_status}

    @app.post("/documents/cancel-running", status_code=202)
    async def cancel_running() -> dict:
        requested: list[str] = []
        failed: list[dict] = []
        running = list(RUNNING_STATUSES)
        # Gom danh sách trước, tránh phân trang lệch khi trạng thái đổi giữa chừng
        recs, offset = [], 0
        while True:
            page, total = repo.list(status=running, limit=200, offset=offset)
            recs += page
            offset += 200
            if offset >= total:
                break
        for rec in recs:
            try:
                await wf.cancel(rec.doc_id, _wid(rec))
                requested.append(rec.doc_id)
            except Exception as exc:
                failed.append({"doc_id": rec.doc_id, "detail": str(exc) or type(exc).__name__})
        return {"requested": requested, "failed": failed}

    def _must_get(doc_id: str) -> DocumentRecord:
        rec = repo.get(doc_id)
        if rec is None:
            raise HTTPException(404, "Không tìm thấy tài liệu")
        return rec

    def _wid(rec: DocumentRecord) -> str:
        return active_workflow_id(rec.doc_id, rec.status, rec.index_version)

    @app.get("/documents/{doc_id}")
    async def get_document(doc_id: str) -> dict:
        rec = _must_get(doc_id)
        out = _doc_json(rec)
        out["progress"] = None
        if rec.status in RUNNING_STATUSES:
            try:
                out["progress"] = await wf.get_progress(doc_id, _wid(rec))
            except Exception:  # Temporal chưa sẵn sàng thì vẫn trả dữ liệu từ DB
                out["progress"] = None
        return out

    @app.get("/", include_in_schema=False)
    def ui() -> HTMLResponse:
        """Trang upload đơn giản, gọi chính các endpoint bên dưới."""
        return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))

    @app.get("/documents/{doc_id}/markdown", response_class=PlainTextResponse)
    def get_markdown(doc_id: str) -> PlainTextResponse:
        """Markdown cuối của tài liệu (có sau bước finalize, trước khi index xong)."""
        _must_get(doc_id)
        key = keys.md_key(doc_id)
        if not storage.exists(key):
            raise HTTPException(404, "Tài liệu chưa có Markdown")
        return PlainTextResponse(
            storage.get(key).decode("utf-8"), media_type="text/markdown; charset=utf-8"
        )

    @app.get("/documents/{doc_id}/raw")
    def get_raw(doc_id: str) -> Response:
        """Tải file gốc đã upload."""
        rec = _must_get(doc_id)
        key = keys.raw_key(doc_id, rec.file_name)
        if not storage.exists(key):
            raise HTTPException(404, "Không có file gốc")
        return Response(
            storage.get(key),
            media_type=rec.mime or "application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(rec.file_name)}"},
        )

    @app.get("/documents/{doc_id}/chunks")
    def get_chunks(
        doc_id: str,
        version: int | None = Query(None, ge=1),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> dict:
        rec = _must_get(doc_id)
        ver = version if version is not None else rec.index_version
        batches = []
        for k in storage.list_keys(f"chunks/{doc_id}/v{ver}/"):
            m = _BATCH_RE.search(k)
            if m:
                batches.append((int(m.group(1)), k))
        if not batches:
            raise HTTPException(404, f"Không có chunk của version {ver}")
        rows = []
        for _, k in sorted(batches):
            rows += [json.loads(ln) for ln in storage.get(k).decode("utf-8").splitlines() if ln]
        rows.sort(key=lambda r: r["chunk_index"])
        return {
            "doc_id": doc_id,
            "index_version": ver,
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "items": rows[offset : offset + limit],
        }

    @app.post("/documents/{doc_id}/review")
    async def review(doc_id: str, decision: Literal["approve", "reject"] = Query(...)) -> dict:
        rec = _must_get(doc_id)
        if rec.status != "NEEDS_REVIEW":
            raise HTTPException(409, f"Tài liệu đang ở trạng thái {rec.status}, không cần duyệt")
        await wf.review_decision(doc_id, decision)
        return {"doc_id": doc_id, "decision": decision}

    @app.post("/documents/{doc_id}/reindex", status_code=202)
    async def reindex(doc_id: str) -> dict:
        rec = _must_get(doc_id)
        if rec.status != "INDEXED":
            raise HTTPException(409, f"Chỉ re-index tài liệu đã INDEXED, hiện là {rec.status}")
        new_version = rec.index_version + 1
        await wf.start_reindex(
            ReindexInput(
                doc_id=doc_id,
                file_name=rec.file_name,
                index_version=new_version,
                chunk_tokens=settings.chunk_tokens,
                chunk_overlap=settings.chunk_overlap,
                batch_size=settings.chunk_batch_size,
                embedding_model=settings.embed_model,
            )
        )
        return {"doc_id": doc_id, "index_version": new_version}

    @app.post("/documents/{doc_id}/cancel", status_code=202)
    async def cancel(doc_id: str) -> dict:
        rec = _must_get(doc_id)
        if rec.status not in RUNNING_STATUSES:
            raise HTTPException(409, f"Tài liệu đã {rec.status}, không huỷ được")
        await wf.cancel(doc_id, _wid(rec))
        return {"doc_id": doc_id, "cancel_requested": True}

    return app


def create_default_app() -> FastAPI:
    """Factory cho uvicorn: dựng phụ thuộc thật từ biến môi trường."""
    from ingest.core.config import get_settings
    from ingest.core.db import session_factory
    from ingest.core.storage import S3Storage

    s = get_settings()
    storage = S3Storage(s.s3_endpoint, s.s3_access_key, s.s3_secret_key, s.s3_bucket, s.s3_region)
    storage.ensure_bucket()
    repo = session_factory(s.database_url)
    wf = _LazyWorkflowClient(s.temporal_address, s.temporal_namespace, s.ingest_tq)
    return create_app(storage, repo, wf, s)


class _LazyWorkflowClient:
    """Kết nối Temporal ở lần gọi đầu (trong event loop của uvicorn)."""

    def __init__(self, address: str, namespace: str, task_queue: str) -> None:
        self._args = (address, namespace, task_queue)
        self._inner: WorkflowClient | None = None

    async def _get(self) -> WorkflowClient:
        if self._inner is None:
            from ingest.api.workflow_client import TemporalWorkflowClient

            self._inner = await TemporalWorkflowClient.connect(*self._args)
        return self._inner

    async def start_ingest(self, inp: IngestInput) -> None:
        await (await self._get()).start_ingest(inp)

    async def start_reindex(self, inp: ReindexInput) -> None:
        await (await self._get()).start_reindex(inp)

    async def get_progress(self, doc_id: str, workflow_id: str | None = None) -> str | None:
        return await (await self._get()).get_progress(doc_id, workflow_id)

    async def review_decision(self, doc_id: str, decision: str) -> None:
        await (await self._get()).review_decision(doc_id, decision)

    async def cancel(self, doc_id: str, workflow_id: str | None = None) -> None:
        await (await self._get()).cancel(doc_id, workflow_id)
