"""DocumentIngestionWorkflow: bước 1-8 trong docs/c4-model.md. Không I/O."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from ingest.core import errors as E
    from ingest.core import retry as R
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
        StatusUpdate,
    )

INGEST_TQ = "ingest-tq"
CONVERT_TQ = "convert-tq"
INDEX_TQ = "index-tq"


async def set_status(
    doc_id: str,
    status: str,
    error_code: str | None = None,
    chunk_count: int | None = None,
    index_version: int | None = None,
    embedding_model: str | None = None,
) -> None:
    await workflow.execute_activity(
        "update_status",
        StatusUpdate(doc_id, status, error_code, chunk_count, index_version, embedding_model),
        task_queue=INGEST_TQ,
        start_to_close_timeout=R.T_STATUS,
        retry_policy=R.RETRY_STATUS,
    )


async def run_index_phase(
    doc_id: str,
    file_name: str,
    index_version: int,
    embedding_model: str,
    chunk_input: ChunkInput,
) -> int:
    """Bước 6-8: chunk, embed fan-out, cleanup. Trả về số chunk. Ghi INDEXING/INDEXED."""
    await set_status(doc_id, "INDEXING", index_version=index_version)
    chunks = await workflow.execute_activity(
        "chunk_markdown",
        chunk_input,
        result_type=ChunkResult,
        task_queue=INDEX_TQ,
        start_to_close_timeout=R.T_CHUNK,
        retry_policy=R.RETRY_CHUNK,
    )
    await asyncio.gather(
        *[
            workflow.execute_activity(
                "embed_and_upsert",
                EmbedBatch(doc_id, index_version, i),
                result_type=EmbedResult,
                task_queue=INDEX_TQ,
                start_to_close_timeout=R.T_EMBED,
                retry_policy=R.RETRY_EMBED,
            )
            for i in range(chunks.batch_count)
        ]
    )
    await workflow.execute_activity(
        "cleanup_old_chunks",
        CleanupInput(doc_id, index_version),
        result_type=CleanupResult,
        task_queue=INDEX_TQ,
        start_to_close_timeout=R.T_CLEANUP,
        retry_policy=R.RETRY_CLEANUP,
    )
    await set_status(
        doc_id,
        "INDEXED",
        chunk_count=chunks.chunk_count,
        index_version=index_version,
        embedding_model=embedding_model or None,
    )
    return chunks.chunk_count


def failed_run(code: str) -> ApplicationError:
    """Để run kết thúc ở trạng thái Failed (không phải Completed), nếu không
    WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY sẽ chặn việc upload lại."""
    return ApplicationError(f"Ingest thất bại: {code}", type=code, non_retryable=True)


def error_code_of(err: ActivityError) -> str:
    cause = err.cause
    if isinstance(cause, ApplicationError) and cause.type:
        return cause.type
    return "ACTIVITY_FAILED"


@workflow.defn(name="DocumentIngestionWorkflow")
class DocumentIngestionWorkflow:
    def __init__(self) -> None:
        self._progress = "RECEIVED"
        self._review: str | None = None  # "approve" | "reject"

    @workflow.query(name="get_progress")
    def get_progress(self) -> str:
        return self._progress

    @workflow.signal(name="review_decision")
    def review_decision(self, decision: str) -> None:
        self._review = decision

    async def _status(self, status: str, **kw) -> None:
        self._progress = status
        await set_status(self._doc_id, status, **kw)

    @workflow.run
    async def run(self, inp: IngestInput) -> IngestResult:
        self._doc_id = inp.doc_id
        try:
            return await self._run(inp)
        except ActivityError as err:
            if isinstance(err.cause, CancelledError):  # huỷ khi activity đang chạy
                await self._status("CANCELLED")
                raise asyncio.CancelledError() from err
            code = error_code_of(err)
            await self._status("FAILED", error_code=code)
            raise failed_run(code) from err
        except asyncio.CancelledError:
            # activity mới sau khi bắt CancelledError vẫn chạy được
            await self._status("CANCELLED")
            raise

    async def _run(self, inp: IngestInput) -> IngestResult:
        await self._status("CONVERTING")
        fmt = await workflow.execute_activity(
            "detect_format",
            inp,
            result_type=FormatInfo,
            task_queue=CONVERT_TQ,
            start_to_close_timeout=R.T_DETECT,
            retry_policy=R.RETRY_DETECT,
        )

        ocr_batches = [
            OcrBatch(inp.doc_id, pages, i, inp.raw_key, fmt.kind, inp.pipeline_version)
            for i, pages in enumerate(fmt.ocr_page_batches)
        ]
        parse_coro = workflow.execute_activity(
            "parse_document",
            inp,
            result_type=PartResult,
            task_queue=CONVERT_TQ,
            start_to_close_timeout=R.T_PARSE,
            heartbeat_timeout=R.HEARTBEAT,
            retry_policy=R.RETRY_PARSE,
        )
        ocr_coros = [
            workflow.execute_activity(
                "ocr_pages",
                b,
                result_type=OcrResult,
                task_queue=CONVERT_TQ,
                start_to_close_timeout=R.T_OCR,
                heartbeat_timeout=R.HEARTBEAT,
                retry_policy=R.RETRY_OCR,
            )
            for b in ocr_batches
        ]
        part, *ocr = await asyncio.gather(parse_coro, *ocr_coros)

        if inp.review_enabled and ocr and min(r.confidence for r in ocr) < inp.min_ocr_confidence:
            await self._status("NEEDS_REVIEW")
            try:
                await workflow.wait_condition(
                    lambda: self._review is not None,
                    timeout=timedelta(days=inp.review_timeout_days),
                )
            except TimeoutError:
                self._review = "reject"
            if self._review != "approve":
                await self._status("FAILED", error_code=E.OCR_REJECTED)
                raise failed_run(E.OCR_REJECTED)
            self._progress = "CONVERTING"

        await workflow.execute_activity(
            "finalize_markdown",
            FinalizeInput(inp.doc_id, inp.file_name, [r.batch_index for r in ocr], part.page_count),
            result_type=FinalizeResult,
            task_queue=CONVERT_TQ,
            start_to_close_timeout=R.T_FINALIZE,
            retry_policy=R.RETRY_FINALIZE,
        )
        await self._status("CONVERTED")

        self._progress = "INDEXING"
        count = await run_index_phase(
            inp.doc_id,
            inp.file_name,
            inp.index_version,
            inp.embedding_model,
            ChunkInput(inp.doc_id, inp.file_name, inp.index_version),
        )
        self._progress = "INDEXED"
        return IngestResult(inp.doc_id, status="INDEXED", chunk_count=count)
