"""Ảnh chụp các task queue trên Temporal cho trang Hàng đợi.

Mỗi queue có hai phần: workflow task và activity task. Với mỗi phần lấy worker đang
poll và số liệu backlog. Kèm danh sách workflow đang chạy cùng activity đang chờ/chạy.
"""

import asyncio
from datetime import UTC, datetime
from typing import Protocol

from temporalio.api.enums.v1 import PendingActivityState, TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client

# Activity nào chạy trên queue nào; khớp workflows/ingestion.py ở package index.
# api không import index nên giữ bảng này ở đây.
ACTIVITY_QUEUE = {
    "detect_format": "convert-tq",
    "parse_document": "convert-tq",
    "ocr_pages": "convert-tq",
    "finalize_markdown": "convert-tq",
    "chunk_markdown": "index-tq",
    "embed_and_upsert": "index-tq",
    "cleanup_old_chunks": "index-tq",
    "update_status": "ingest-tq",
}

MAX_RUNNING = 50  # mỗi workflow tốn một lần describe

_STATE = {
    PendingActivityState.PENDING_ACTIVITY_STATE_SCHEDULED: "SCHEDULED",
    PendingActivityState.PENDING_ACTIVITY_STATE_STARTED: "STARTED",
    PendingActivityState.PENDING_ACTIVITY_STATE_CANCEL_REQUESTED: "CANCEL_REQUESTED",
    PendingActivityState.PENDING_ACTIVITY_STATE_PAUSED: "PAUSED",
    PendingActivityState.PENDING_ACTIVITY_STATE_PAUSE_REQUESTED: "PAUSE_REQUESTED",
}


class QueueInspector(Protocol):
    async def snapshot(self) -> dict: ...


def _iso(ts) -> str | None:
    """Timestamp protobuf sang ISO UTC; trường rỗng trả None."""
    if ts is None or (ts.seconds == 0 and ts.nanos == 0):
        return None
    return ts.ToDatetime(tzinfo=UTC).isoformat()


def _doc_id_of(workflow_id: str) -> str | None:
    """ingest-<doc_id> hoặc reindex-<doc_id>-v<n>."""
    if workflow_id.startswith("ingest-"):
        return workflow_id.removeprefix("ingest-")
    if workflow_id.startswith("reindex-"):
        return workflow_id.removeprefix("reindex-").rsplit("-v", 1)[0]
    return None


class TemporalQueueInspector:
    def __init__(self, client: Client, namespace: str, queues: list[str]) -> None:
        """queues[0] là queue của workflow; các queue sau chỉ có activity."""
        self._c = client
        self._ns = namespace
        self._queues = queues

    async def _describe(self, name: str, kind: TaskQueueType.ValueType) -> dict:
        r = await self._c.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=self._ns,
                task_queue=TaskQueue(name=name),
                task_queue_type=kind,
                report_stats=True,
            )
        )
        s = r.stats
        return {
            "pollers": [
                {"identity": p.identity, "last_access": _iso(p.last_access_time)} for p in r.pollers
            ],
            "backlog": s.approximate_backlog_count,
            "backlog_age_s": s.approximate_backlog_age.ToTimedelta().total_seconds(),
            "add_rate": round(s.tasks_add_rate, 2),
            "dispatch_rate": round(s.tasks_dispatch_rate, 2),
        }

    async def _queue(self, name: str) -> dict:
        wf, act = await asyncio.gather(
            self._describe(name, TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW),
            self._describe(name, TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY),
        )
        return {
            "name": name,
            "expects_workflow": name == self._queues[0],
            "workflow": wf,
            "activity": act,
        }

    async def _running_one(self, wid: str, run_id: str | None, wtype: str, started) -> dict:
        d = await self._c.get_workflow_handle(wid, run_id=run_id).describe()
        acts = []
        for a in d.raw_description.pending_activities:
            name = a.activity_type.name
            acts.append(
                {
                    "name": name,
                    "task_queue": ACTIVITY_QUEUE.get(name),
                    "state": _STATE.get(a.state, "UNKNOWN"),
                    "attempt": a.attempt,
                    "scheduled_at": _iso(a.scheduled_time),
                    "started_at": _iso(a.last_started_time),
                    "worker": a.last_worker_identity or None,
                    "last_failure": a.last_failure.message or None,
                }
            )
        return {
            "workflow_id": wid,
            "workflow_type": wtype,
            "doc_id": _doc_id_of(wid),
            "started_at": started.isoformat() if started else None,
            "activities": acts,
        }

    async def _running(self) -> tuple[list[dict], bool]:
        found = []
        async for w in self._c.list_workflows('ExecutionStatus="Running"', limit=MAX_RUNNING + 1):
            found.append(w)
        truncated = len(found) > MAX_RUNNING
        found = found[:MAX_RUNNING]
        rows = await asyncio.gather(
            *[self._running_one(w.id, w.run_id, w.workflow_type, w.start_time) for w in found],
            return_exceptions=True,
        )
        # workflow vừa xong giữa lúc list và describe thì bỏ qua
        out = [r for r in rows if isinstance(r, dict)]
        out.sort(key=lambda r: r["started_at"] or "")
        return out, truncated

    async def snapshot(self) -> dict:
        queues, (running, truncated) = await asyncio.gather(
            asyncio.gather(*[self._queue(q) for q in self._queues]), self._running()
        )
        return {
            "fetched_at": datetime.now(UTC).isoformat(),
            "queues": list(queues),
            "running": running,
            "running_truncated": truncated,
        }


class LazyQueueInspector:
    """Kết nối Temporal ở lần gọi đầu; lỗi kết nối thì lần sau thử lại."""

    def __init__(self, address: str, namespace: str, queues: list[str]) -> None:
        """queues[0] là queue của workflow, như TemporalQueueInspector."""
        self._args = (address, namespace, queues)
        self._inner: TemporalQueueInspector | None = None

    async def snapshot(self) -> dict:
        if self._inner is None:
            address, ns, queues = self._args
            self._inner = TemporalQueueInspector(
                await Client.connect(address, namespace=ns), ns, queues
            )
        return await self._inner.snapshot()
