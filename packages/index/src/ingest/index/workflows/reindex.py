"""ReindexWorkflow: chỉ bước 6-8, Markdown đã có sẵn trên storage."""

import asyncio

from temporalio import workflow
from temporalio.exceptions import ActivityError, CancelledError

with workflow.unsafe.imports_passed_through():
    from ingest.core.models import ChunkInput, IngestResult, ReindexInput
    from ingest.index.workflows.ingestion import (
        error_code_of,
        failed_run,
        run_index_phase,
        set_status,
    )


@workflow.defn(name="ReindexWorkflow")
class ReindexWorkflow:
    def __init__(self) -> None:
        self._progress = "INDEXING"

    @workflow.query(name="get_progress")
    def get_progress(self) -> str:
        return self._progress

    @workflow.run
    async def run(self, inp: ReindexInput) -> IngestResult:
        try:
            count = await run_index_phase(
                inp.doc_id,
                inp.file_name,
                inp.index_version,
                inp.embedding_model,
                ChunkInput(
                    inp.doc_id,
                    inp.file_name,
                    inp.index_version,
                    inp.chunk_tokens,
                    inp.chunk_overlap,
                    inp.batch_size,
                ),
            )
        except ActivityError as err:
            if isinstance(err.cause, CancelledError):  # huỷ khi activity đang chạy
                self._progress = "CANCELLED"
                await set_status(inp.doc_id, "CANCELLED")
                raise asyncio.CancelledError() from err
            code = error_code_of(err)
            self._progress = "FAILED"
            await set_status(inp.doc_id, "FAILED", error_code=code)
            raise failed_run(code) from err
        except asyncio.CancelledError:
            self._progress = "CANCELLED"
            await set_status(inp.doc_id, "CANCELLED")
            raise
        self._progress = "INDEXED"
        return IngestResult(inp.doc_id, status="INDEXED", chunk_count=count)
