"""Lớp mỏng trên temporalio Client. Gọi workflow theo tên, không import class workflow."""

from typing import Protocol

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from ingest.core.models import IngestInput, ReindexInput

INGEST_WORKFLOW = "DocumentIngestionWorkflow"
REINDEX_WORKFLOW = "ReindexWorkflow"
EXECUTION_TIMEOUT_SECONDS = 6 * 3600


def ingest_workflow_id(doc_id: str) -> str:
    return f"ingest-{doc_id}"


def reindex_workflow_id(doc_id: str, index_version: int) -> str:
    return f"reindex-{doc_id}-v{index_version}"


def active_workflow_id(doc_id: str, status: str, index_version: int) -> str:
    """Workflow đang chạy của tài liệu, suy ra từ Metadata DB nên API restart vẫn tìm được.

    Reindex ghi INDEXING với index_version mới (>= 2) ngay khi bắt đầu; ingest lần đầu luôn là v1.
    """
    if status == "INDEXING" and index_version >= 2:
        return reindex_workflow_id(doc_id, index_version)
    return ingest_workflow_id(doc_id)


class WorkflowClient(Protocol):
    async def start_ingest(self, inp: IngestInput) -> None: ...
    async def start_reindex(self, inp: ReindexInput) -> None: ...
    async def get_progress(self, doc_id: str, workflow_id: str | None = None) -> str | None: ...
    async def review_decision(self, doc_id: str, decision: str) -> None: ...
    async def cancel(self, doc_id: str, workflow_id: str | None = None) -> None: ...


class TemporalWorkflowClient:
    def __init__(self, client: Client, task_queue: str = "ingest-tq") -> None:
        self._c = client
        self._tq = task_queue

    @classmethod
    async def connect(
        cls, address: str, namespace: str = "default", task_queue: str = "ingest-tq"
    ) -> "TemporalWorkflowClient":
        return cls(await Client.connect(address, namespace=namespace), task_queue)

    async def start_ingest(self, inp: IngestInput) -> None:
        from datetime import timedelta

        await self._c.start_workflow(
            INGEST_WORKFLOW,
            inp,
            id=ingest_workflow_id(inp.doc_id),
            task_queue=self._tq,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            execution_timeout=timedelta(seconds=EXECUTION_TIMEOUT_SECONDS),
        )

    async def start_reindex(self, inp: ReindexInput) -> None:
        from datetime import timedelta

        wid = reindex_workflow_id(inp.doc_id, inp.index_version)
        await self._c.start_workflow(
            REINDEX_WORKFLOW,
            inp,
            id=wid,
            task_queue=self._tq,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            execution_timeout=timedelta(seconds=EXECUTION_TIMEOUT_SECONDS),
        )

    async def get_progress(self, doc_id: str, workflow_id: str | None = None) -> str | None:
        try:
            wid = workflow_id or ingest_workflow_id(doc_id)
            return await self._c.get_workflow_handle(wid).query("get_progress", result_type=str)
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                return None
            raise

    async def review_decision(self, doc_id: str, decision: str) -> None:
        await self._c.get_workflow_handle(ingest_workflow_id(doc_id)).signal(
            "review_decision", decision
        )

    async def cancel(self, doc_id: str, workflow_id: str | None = None) -> None:
        await self._c.get_workflow_handle(workflow_id or ingest_workflow_id(doc_id)).cancel()
