"""Workflow: song song parse+OCR, fan-out lớn, huỷ giữa INDEXING, retry theo bảng spec."""

import asyncio
import uuid

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from ingest.core import errors as E
from ingest.core.models import (
    CleanupInput,
    CleanupResult,
    EmbedBatch,
    EmbedResult,
    FinalizeInput,
    FinalizeResult,
    IngestInput,
    OcrBatch,
    OcrResult,
    PartResult,
    ReindexInput,
)
from ingest.index.workflows.reindex import ReindexWorkflow
from test_workflows import Fakes, failure_code, new_input, run_with, start


@pytest.fixture
async def env():
    try:
        e = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:
        pytest.skip(f"Không khởi động được Temporal test server: {exc!r}")
    yield e
    await e.shutdown()


def replace(f: Fakes, fn):
    """Thay activity cùng tên bằng fn (đã @activity.defn)."""
    orig = f.activities

    def patched():
        return [a for a in orig() if a.__name__ != fn.__name__] + [fn]

    f.activities = patched


async def wait_for(pred, timeout=10.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not pred():
        assert loop.time() < end, "điều kiện không đạt kịp thời"
        await asyncio.sleep(0.02)


async def test_parse_and_ocr_batches_run_concurrently(env):
    f = Fakes(ocr_batches=3)
    running: set[str] = set()
    peak = {"n": 0}
    gate = asyncio.Event()

    @activity.defn(name="parse_document")
    async def parse_document(inp: IngestInput) -> PartResult:
        running.add("parse")
        peak["n"] = max(peak["n"], len(running))
        await asyncio.wait_for(gate.wait(), 15)  # chỉ mở khi cả 3 OCR cũng đang chạy
        running.discard("parse")
        return PartResult(inp.doc_id, "md-raw/x/text.md", 4)

    @activity.defn(name="ocr_pages")
    async def ocr_pages(b: OcrBatch) -> OcrResult:
        running.add(f"ocr{b.batch_index}")
        peak["n"] = max(peak["n"], len(running))
        if {"parse", "ocr0", "ocr1", "ocr2"} <= running:
            gate.set()
        await asyncio.wait_for(gate.wait(), 15)
        running.discard(f"ocr{b.batch_index}")
        return OcrResult(b.doc_id, b.batch_index, "k", 0.9)

    replace(f, parse_document)
    replace(f, ocr_pages)

    async def body():
        return await (await start(env, new_input())).result()

    res = await run_with(env, f, body)
    assert res.status == "INDEXED" and peak["n"] == 4


async def test_finalize_receives_ocr_batch_indices_and_page_count_from_parse(env):
    f = Fakes(ocr_batches=3)
    seen: list[FinalizeInput] = []

    @activity.defn(name="finalize_markdown")
    async def finalize_markdown(inp: FinalizeInput) -> FinalizeResult:
        seen.append(inp)
        return FinalizeResult(inp.doc_id, "md/x.md", 5)

    replace(f, finalize_markdown)

    async def body():
        return await (await start(env, new_input())).result()

    await run_with(env, f, body)
    assert sorted(seen[0].ocr_batches) == [0, 1, 2] and seen[0].page_count == 4
    assert seen[0].file_name == "a.pdf"


async def test_ocr_batches_receive_pages_raw_key_and_kind_from_detect(env):
    f = Fakes(ocr_batches=2)
    got: list[OcrBatch] = []

    @activity.defn(name="ocr_pages")
    async def ocr_pages(b: OcrBatch) -> OcrResult:
        got.append(b)
        return OcrResult(b.doc_id, b.batch_index, "k", 0.9)

    replace(f, ocr_pages)

    async def body():
        return await (await start(env, new_input())).result()

    await run_with(env, f, body)
    assert sorted((b.batch_index, tuple(b.pages)) for b in got) == [(0, (0,)), (1, (1,))]
    assert all(b.raw_key == "raw/x/a.pdf" and b.kind == "pdf" for b in got)


async def test_text_only_document_runs_no_ocr_activity(env):
    f = Fakes(ocr_batches=0)

    async def body():
        return await (await start(env, new_input(review_enabled=True))).result()

    res = await run_with(env, f, body)
    assert res.status == "INDEXED"
    assert "ocr_pages" not in f.calls and "NEEDS_REVIEW" not in f.status_names


@pytest.mark.parametrize(
    ("confs", "min_conf", "expect_review"),
    [([0.9, 0.2], 0.6, True), ([0.9, 0.7], 0.6, False), ([0.6, 0.9], 0.6, False)],
)
async def test_review_uses_lowest_batch_confidence_and_strict_threshold(
    env, confs, min_conf, expect_review
):
    f = Fakes(ocr_batches=2)

    @activity.defn(name="ocr_pages")
    async def ocr_pages(b: OcrBatch) -> OcrResult:
        return OcrResult(b.doc_id, b.batch_index, "k", confs[b.batch_index])

    replace(f, ocr_pages)

    async def body():
        h = await start(env, new_input(review_enabled=True, min_ocr_confidence=min_conf))
        if expect_review:
            await wait_for(lambda: "NEEDS_REVIEW" in f.status_names)
            await h.signal("review_decision", "approve")
        return await h.result()

    res = await run_with(env, f, body)
    assert res.status == "INDEXED"
    assert ("NEEDS_REVIEW" in f.status_names) is expect_review


async def test_many_embed_batches_fan_out_every_index_once_before_cleanup(env):
    f = Fakes(batch_count=40)
    order: list[str] = []
    seen: list[int] = []

    @activity.defn(name="embed_and_upsert")
    async def embed_and_upsert(b: EmbedBatch) -> EmbedResult:
        order.append("embed")
        seen.append(b.batch_index)
        await asyncio.sleep(0.01)
        return EmbedResult(b.doc_id, b.batch_index, 10)

    @activity.defn(name="cleanup_old_chunks")
    async def cleanup_old_chunks(inp: CleanupInput) -> CleanupResult:
        order.append("cleanup")
        return CleanupResult(inp.doc_id, 0)

    replace(f, embed_and_upsert)
    replace(f, cleanup_old_chunks)

    async def body():
        return await (await start(env, new_input(index_version=3))).result()

    res = await run_with(env, f, body)
    assert res.chunk_count == 400
    assert sorted(seen) == list(range(40))
    assert order.count("cleanup") == 1 and order[-1] == "cleanup"
    assert f.status_names[-2:] == ["INDEXING", "INDEXED"]


async def test_zero_chunk_document_skips_embed_but_still_finishes(env):
    f = Fakes(batch_count=0)

    async def body():
        return await (await start(env, new_input())).result()

    res = await run_with(env, f, body)
    assert res.chunk_count == 0 and "embed_and_upsert" not in f.calls
    assert f.statuses[-1].status == "INDEXED" and f.statuses[-1].chunk_count == 0


async def test_cancel_during_indexing_records_cancelled_and_skips_cleanup(env):
    f = Fakes(batch_count=3)
    started = asyncio.Event()

    @activity.defn(name="embed_and_upsert")
    async def embed_and_upsert(b: EmbedBatch) -> EmbedResult:
        started.set()
        try:
            for _ in range(200):
                activity.heartbeat()
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        raise RuntimeError("không nhận được lệnh huỷ")

    replace(f, embed_and_upsert)

    async def body():
        h = await start(env, new_input())
        await asyncio.wait_for(started.wait(), 15)
        await h.cancel()
        with pytest.raises(WorkflowFailureError):
            await h.result()

    await run_with(env, f, body)
    assert f.status_names[-1] == "CANCELLED", f.statuses
    assert "INDEXING" in f.status_names and "INDEXED" not in f.status_names
    assert "cleanup_old_chunks" not in f.calls  # version cũ còn nguyên cho RAG


async def test_cancel_during_converting_records_cancelled(env):
    f = Fakes(ocr_batches=0)  # chỉ parse đang chạy: tránh đua với activity khác
    started = asyncio.Event()

    @activity.defn(name="parse_document")
    async def parse_document(inp: IngestInput) -> PartResult:
        started.set()
        for _ in range(200):  # chặn trên để worker luôn tắt được
            activity.heartbeat()
            await asyncio.sleep(0.05)
        raise RuntimeError("không nhận được lệnh huỷ")

    replace(f, parse_document)

    async def body():
        h = await start(env, new_input())
        await asyncio.wait_for(started.wait(), 15)
        await h.cancel()
        with pytest.raises(WorkflowFailureError):
            await h.result()

    await run_with(env, f, body)
    assert f.status_names[-1] == "CANCELLED" and "FAILED" not in f.status_names


async def test_cancel_during_reindex_records_cancelled_not_failed(env):
    f = Fakes(batch_count=2)
    started = asyncio.Event()

    @activity.defn(name="embed_and_upsert")
    async def embed_and_upsert(b: EmbedBatch) -> EmbedResult:
        started.set()
        for _ in range(200):  # chặn trên để worker luôn tắt được
            activity.heartbeat()
            await asyncio.sleep(0.05)
        raise RuntimeError("không nhận được lệnh huỷ")

    replace(f, embed_and_upsert)
    inp = ReindexInput(doc_id="doc-rc", file_name="a.pdf", index_version=2)

    async def body():
        h = await env.client.start_workflow(
            ReindexWorkflow.run, inp, id=f"reindex-{uuid.uuid4().hex[:6]}", task_queue="ingest-tq"
        )
        await asyncio.wait_for(started.wait(), 15)
        await h.cancel()
        with pytest.raises(WorkflowFailureError):
            await h.result()

    await run_with(env, f, body)
    assert f.status_names[-1] == "CANCELLED" and "cleanup_old_chunks" not in f.calls


@pytest.mark.parametrize(
    ("activity_name", "code"),
    [
        ("parse_document", E.FILE_CORRUPTED),
        ("parse_document", E.PASSWORD_PROTECTED),
        ("finalize_markdown", E.EMPTY_DOCUMENT),
        ("embed_and_upsert", E.EMBED_INPUT_TOO_LONG),
        ("detect_format", E.FILE_CORRUPTED),
    ],
)
async def test_each_non_retryable_code_fails_after_single_attempt(env, activity_name, code):
    f = Fakes(batch_count=1)
    attempts = {"n": 0}

    async def boom(*_a):
        attempts["n"] += 1
        raise ApplicationError("x", type=code, non_retryable=True)

    boom.__name__ = activity_name
    replace(f, activity.defn(name=activity_name)(boom_for(activity_name, boom)))

    async def body():
        return await failure_code(await start(env, new_input()))

    assert await run_with(env, f, body) == code
    assert attempts["n"] == 1
    assert f.statuses[-1].status == "FAILED" and f.statuses[-1].error_code == code
    assert "cleanup_old_chunks" not in f.calls


def boom_for(name, boom):
    """Chữ ký đúng theo từng activity (Temporal đọc type hint để decode)."""
    if name == "finalize_markdown":

        async def fn(inp: FinalizeInput) -> FinalizeResult:
            await boom()

    elif name == "embed_and_upsert":

        async def fn(b: EmbedBatch) -> EmbedResult:
            await boom()

    else:

        async def fn(inp: IngestInput) -> PartResult:
            await boom()

    fn.__name__ = name
    return fn


@pytest.mark.parametrize(
    ("activity_name", "attempts_expected"),
    [("parse_document", 3), ("finalize_markdown", 3), ("embed_and_upsert", 8)],
)
async def test_retryable_error_exhausts_attempts_from_spec_table(
    env, activity_name, attempts_expected
):
    f = Fakes(batch_count=1)
    attempts = {"n": 0}

    async def boom(*_a):
        attempts["n"] += 1
        raise RuntimeError("tạm thời")

    replace(f, activity.defn(name=activity_name)(boom_for(activity_name, boom)))

    async def body():
        return await failure_code(await start(env, new_input()))

    await run_with(env, f, body)
    assert attempts["n"] == attempts_expected
    assert f.statuses[-1].status == "FAILED"


async def test_transient_embed_failure_is_retried_then_succeeds(env):
    f = Fakes(batch_count=1)
    attempts = {"n": 0}

    @activity.defn(name="embed_and_upsert")
    async def embed_and_upsert(b: EmbedBatch) -> EmbedResult:
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise RuntimeError("429 Too Many Requests")
        return EmbedResult(b.doc_id, b.batch_index, 10)

    replace(f, embed_and_upsert)

    async def body():
        return await (await start(env, new_input())).result()

    res = await run_with(env, f, body)
    assert res.status == "INDEXED" and attempts["n"] == 4
    assert "FAILED" not in f.status_names


async def test_workflow_run_is_deterministic_under_replay(env):
    """Replay lịch sử bằng code hiện tại không được lỗi non-determinism."""
    from temporalio.worker import Replayer

    from ingest.index.workflows.ingestion import DocumentIngestionWorkflow

    f = Fakes(confidence=0.1, ocr_batches=2)

    async def body():
        h = await start(env, new_input(review_enabled=True))
        await wait_for(lambda: "NEEDS_REVIEW" in f.status_names)
        await h.signal("review_decision", "approve")
        await h.result()
        return await h.fetch_history()

    history = await run_with(env, f, body)
    await Replayer(workflows=[DocumentIngestionWorkflow]).replay_workflow(history)


async def test_two_documents_run_in_parallel_without_mixing_status(env):
    # hai doc khác nhau chạy song song không lẫn trạng thái
    f = Fakes()
    a, b = new_input(), new_input()

    async def body():
        ha, hb = await start(env, a), await start(env, b)
        return await ha.result(), await hb.result()

    ra, rb = await run_with(env, f, body)
    assert ra.doc_id == a.doc_id and rb.doc_id == b.doc_id
    assert {s.doc_id for s in f.statuses} == {a.doc_id, b.doc_id}
    assert [s.status for s in f.statuses if s.doc_id == a.doc_id][-1] == "INDEXED"
