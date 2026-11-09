"""Activity update_status (chạy ở ingest-tq). Ghi giá trị tuyệt đối nên idempotent."""

import asyncio

from temporalio import activity

from ingest.core.db import DocumentRepository
from ingest.core.models import StatusUpdate


class StatusActivities:
    def __init__(self, repo: DocumentRepository) -> None:
        self.repo = repo

    @activity.defn(name="update_status")
    async def update_status(self, upd: StatusUpdate) -> None:
        await asyncio.to_thread(
            self.repo.set_status,
            upd.doc_id,
            upd.status,
            upd.error_code,
            upd.chunk_count,
            upd.index_version,
            upd.embedding_model,
        )
