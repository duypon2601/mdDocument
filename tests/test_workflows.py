"""Test workflow với fake activity cùng tên, chạy trên test server time-skipping."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from ingest.core import errors as E
from ingest.core.models import (
    ChunkInput,
    ChunkResult,
    CleanupInput,
    CleanupResult,
    EmbedBatch,
    EmbedResult,
    FinalizeInput,
    FinalizeResult,
    FormatInfo,
    IngestInput,
    IngestResult,
    OcrBatch,
    OcrResult,
    PartResult,
    ReindexInput,
    StatusUpdate,
)
from ingest.index.workflows.ingestion import DocumentIngestionWorkflow
from ingest.index.workflows.reindex import ReindexWorkflow


class Fakes:
    def __init__(self, confidence=0.9, ocr_batches=2, detect_error=None, batch_count=3):
        self.confidence = confidence
        self.ocr_batches = ocr_batches
        self.detect_error = detect_error
        self.batch_count = batch_count
        self.calls: list[str] = []
        self.statuses: list[StatusUpdate] = []

    def activities(self):
        f = self

        @activity.defn(name="update_status")
        async def update_status(upd: StatusUpdate) -> None:
            f.calls.append("update_status")
            f.statuses.append(upd)

        @activity.defn(name="detect_format")
        async def detect_format(inp: IngestInput) -> FormatInfo:
            f.calls.append("detect_format")
            if f.detect_error:
                raise ApplicationError("bad", type=f.detect_error, non_retryable=True)
            return FormatInfo(
                inp.doc_id,
                kind="pdf",
                page_count=4,
                ocr_page_batches=[[i] for i in range(f.ocr_batches)],
            )

        @activity.defn(name="parse_document")
        async def parse_document(inp: IngestInput) -> PartResult:
            f.calls.append("parse_document")
            return PartResult(inp.doc_id, "md-raw/x/text.md", 4)

        @activity.defn(name="ocr_pages")
        async def ocr_pages(b: OcrBatch) -> OcrResult:
            f.calls.append("ocr_pages")
            return OcrResult(b.doc_id, b.batch_index, "k", f.confidence)

        @activity.defn(name="finalize_markdown")
        async def finalize_markdown(inp: FinalizeInput) -> FinalizeResult:
            f.calls.append("finalize_markdown")
            return FinalizeResult(inp.doc_id, "md/x.md", 100)

        @activity.defn(name="chunk_markdown")
        async def chunk_markdown(inp: ChunkInput) -> ChunkResult:
            f.calls.append("chunk_markdown")
            return ChunkResult(inp.doc_id, inp.index_version, f.batch_count, f.batch_count * 10)

        @activity.defn(name="embed_and_upsert")
        async def embed_and_upsert(b: EmbedBatch) -> EmbedResult:
            f.calls.append("embed_and_upsert")
            return EmbedResult(b.doc_id, b.batch_index, 10)

        @activity.defn(name="cleanup_old_chunks")
        async def cleanup_old_chunks(inp: CleanupInput) -> CleanupResult:
            f.calls.append("cleanup_old_chunks")
            return CleanupResult(inp.doc_id, 0)

        return [
            update_status,
            detect_format,
            parse_document,
            ocr_pages,
            finalize_markdown,
            chunk_markdown,
            embed_and_upsert,
            cleanup_old_chunks,
        ]

    @property
    def status_names(self) -> list[str]:
        return [s.status for s in self.statuses]


@pytest.fixture
async def env():
    try:
        e = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # không tải được test server (offline)
        pytest.skip(f"Không khởi động được Temporal test server: {exc!r}")
    yield e
    await e.shutdown()


async def failure_code(handle) -> str:
    """Run phải Failed (không phải Completed) để workflow id dùng lại được; trả mã lỗi."""
    with pytest.raises(WorkflowFailureError) as ei:
        await handle.result()
    assert isinstance(ei.value.cause, ApplicationError)
    return ei.value.cause.type


async def run_with(env, fakes: Fakes, body):
    """Một worker chạy cả 3 task queue với activity giả."""
    acts = fakes.activities()
    workers = [
        Worker(
            env.client,
            task_queue=tq,
            workflows=[DocumentIngestionWorkflow, ReindexWorkflow] if tq == "ingest-tq" else [],
            activities=acts,
        )
        for tq in ("ingest-tq", "convert-tq", "index-tq")
    ]
    async with workers[0], workers[1], workers[2]:
        return await body()


def new_input(**kw) -> IngestInput:
    doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    return IngestInput(doc_id=doc_id, file_name="a.pdf", raw_key="raw/x/a.pdf", **kw)


async def start(env, inp, **kw):
    return await env.client.start_workflow(
        DocumentIngestionWorkflow.run, inp, id=f"ingest-{inp.doc_id}", task_queue="ingest-tq", **kw
    )


async def test_happy_path(env):
    f = Fakes()
    inp = new_input(index_version=2, embedding_model="bge-m3")

    async def body():
        h = await start(env, inp)
        return await h.result(), await h.query("get_progress")

    res, progress = await run_with(env, f, body)
    assert isinstance(res, IngestResult)
    assert res.status == "INDEXED" and res.chunk_count == 30
    assert progress == "INDEXED"
    assert f.status_names == ["CONVERTING", "CONVERTED", "INDEXING", "INDEXED"]
    assert f.statuses[-1].chunk_count == 30 and f.statuses[-1].index_version == 2
    assert f.calls.count("ocr_pages") == 2 and f.calls.count("embed_and_upsert") == 3
    assert f.calls.count("cleanup_old_chunks") == 1


async def test_low_confidence_without_review_enabled_continues(env):
    f = Fakes(confidence=0.1)

    async def body():
        return await (await start(env, new_input())).result()

    res = await run_with(env, f, body)
    assert res.status == "INDEXED"
    assert "NEEDS_REVIEW" not in f.status_names


async def _wait_progress(h, expected):
    for _ in range(200):
        if await h.query("get_progress") == expected:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"progress không tới {expected}")


async def test_review_approve(env):
    f = Fakes(confidence=0.1)

    async def body():
        h = await start(env, new_input(review_enabled=True))
        await _wait_progress(h, "NEEDS_REVIEW")
        await h.signal("review_decision", "approve")
        return await h.result()

    res = await run_with(env, f, body)
    assert res.status == "INDEXED"
    assert f.status_names == [
        "CONVERTING", "NEEDS_REVIEW", "CONVERTED", "INDEXING", "INDEXED",
    ]  # fmt: skip


async def test_review_reject(env):
    f = Fakes(confidence=0.1)

    async def body():
        h = await start(env, new_input(review_enabled=True))
        await _wait_progress(h, "NEEDS_REVIEW")
        await h.signal("review_decision", "reject")
        return await failure_code(h)

    code = await run_with(env, f, body)
    assert code == E.OCR_REJECTED
    assert f.statuses[-1].status == "FAILED" and f.statuses[-1].error_code == E.OCR_REJECTED
    assert "chunk_markdown" not in f.calls


async def test_review_timeout_rejects(env):
    f = Fakes(confidence=0.1)

    async def body():
        h = await start(env, new_input(review_enabled=True))
        await _wait_progress(h, "NEEDS_REVIEW")
        # time-skipping: result() tự nhảy qua 7 ngày chờ
        return await failure_code(h)

    code = await run_with(env, f, body)
    assert code == E.OCR_REJECTED
    assert f.statuses[-1].error_code == E.OCR_REJECTED


async def test_non_retryable_error_marks_failed(env):
    f = Fakes(detect_error=E.UNSUPPORTED_FORMAT)

    async def body():
        return await failure_code(await start(env, new_input()))

    code = await run_with(env, f, body)
    assert code == E.UNSUPPORTED_FORMAT
    assert f.calls.count("detect_format") == 1  # không retry
    assert f.statuses[-1].status == "FAILED"
    assert f.statuses[-1].error_code == E.UNSUPPORTED_FORMAT


async def test_cancel_records_cancelled(env):
    f = Fakes(confidence=0.1)

    async def body():
        h = await start(env, new_input(review_enabled=True))
        await _wait_progress(h, "NEEDS_REVIEW")
        await h.cancel()
        with pytest.raises(WorkflowFailureError):
            await h.result()

    await run_with(env, f, body)
    assert f.statuses[-1].status == "CANCELLED"


async def test_reindex_runs_only_index_steps(env):
    f = Fakes(batch_count=2)
    inp = ReindexInput(doc_id="doc-r", file_name="a.pdf", index_version=3, embedding_model="m")

    async def body():
        return await env.client.execute_workflow(
            ReindexWorkflow.run, inp, id=f"reindex-{uuid.uuid4().hex[:6]}", task_queue="ingest-tq",
            execution_timeout=timedelta(hours=6),
        )  # fmt: skip

    res = await run_with(env, f, body)
    assert res.status == "INDEXED" and res.chunk_count == 20
    assert f.status_names == ["INDEXING", "INDEXED"]
    assert set(f.calls) == {
        "update_status", "chunk_markdown", "embed_and_upsert", "cleanup_old_chunks",
    }  # fmt: skip
    assert f.calls.count("embed_and_upsert") == 2


async def test_failed_run_allows_restart_with_same_id(env):
    """Run Failed + ALLOW_DUPLICATE_FAILED_ONLY: start lại cùng workflow id được chấp nhận."""
    from ingest.api.workflow_client import ingest_workflow_id

    inp = new_input()
    wid = ingest_workflow_id(inp.doc_id)

    async def go(handle_fn):
        return await env.client.start_workflow(
            DocumentIngestionWorkflow.run, inp, id=wid, task_queue="ingest-tq",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            execution_timeout=timedelta(hours=6),
        )  # fmt: skip

    f = Fakes(detect_error=E.FILE_CORRUPTED)

    async def body():
        assert await failure_code(await go(None)) == E.FILE_CORRUPTED
        f.detect_error = None
        h = await go(None)  # lần 2 không bị WorkflowAlreadyStartedError
        return await h.result()

    res = await run_with(env, f, body)
    assert res.status == "INDEXED"


async def test_reindex_failure_fails_the_run(env):
    f = Fakes(batch_count=1)
    inp = ReindexInput(doc_id="doc-r", file_name="a.pdf", index_version=2, embedding_model="m")
    orig = f.activities

    def patched():
        acts = orig()

        @activity.defn(name="embed_and_upsert")
        async def boom(b: EmbedBatch) -> EmbedResult:
            raise ApplicationError("dài", type=E.EMBED_INPUT_TOO_LONG, non_retryable=True)

        return [a for a in acts if a.__name__ != "embed_and_upsert"] + [boom]

    f.activities = patched

    async def body():
        h = await env.client.start_workflow(
            ReindexWorkflow.run, inp, id=f"reindex-{uuid.uuid4().hex[:6]}", task_queue="ingest-tq",
            execution_timeout=timedelta(hours=6),
        )  # fmt: skip
        return await failure_code(h)

    assert await run_with(env, f, body) == E.EMBED_INPUT_TOO_LONG
    assert f.statuses[-1].status == "FAILED"
    assert f.statuses[-1].error_code == E.EMBED_INPUT_TOO_LONG
