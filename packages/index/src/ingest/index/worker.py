"""Indexing Worker: một tiến trình, hai Worker.

- ingest-tq: hai workflow và activity update_status (thay Orchestrator Worker cũ).
- index-tq: chunk, embed, upsert. Rate limit đặt trên Worker này theo giới hạn của embedding API,
  nên không làm chậm workflow task hay update_status bên ingest-tq.

Giữ ingest-tq riêng để sau này tách workflow sang tiến trình khác chỉ cần đổi chỗ đăng ký.
"""

from temporalio.client import Client
from temporalio.worker import Worker

from ingest.core.config import Settings
from ingest.core.runtime import make_repo, make_storage, run_main
from ingest.index.activities import IndexActivities
from ingest.index.embedder import OpenAICompatEmbedder
from ingest.index.status import StatusActivities
from ingest.index.vectorstore import VectorStore
from ingest.index.workflows.ingestion import DocumentIngestionWorkflow
from ingest.index.workflows.reindex import ReindexWorkflow


def make_embedder(s: Settings) -> OpenAICompatEmbedder:
    return OpenAICompatEmbedder(s.embed_base_url, s.embed_api_key, s.embed_model, s.embed_dim)


def make_vectors(s: Settings) -> VectorStore:
    from qdrant_client import QdrantClient

    return VectorStore(QdrantClient(url=s.qdrant_url), s.qdrant_collection)


async def build(s: Settings, client: Client) -> list[Worker]:
    status = StatusActivities(make_repo(s))
    workflow_worker = Worker(
        client,
        task_queue=s.ingest_tq,
        workflows=[DocumentIngestionWorkflow, ReindexWorkflow],
        activities=[status.update_status],
    )
    a = IndexActivities(
        make_storage(s), make_embedder(s), make_vectors(s), embed_max_tokens=s.embed_max_tokens
    )
    index_worker = Worker(
        client,
        task_queue=s.index_tq,
        activities=[a.chunk_markdown, a.embed_and_upsert, a.cleanup_old_chunks],
        max_task_queue_activities_per_second=s.index_max_activities_per_second,
    )
    return [workflow_worker, index_worker]


def main() -> None:
    run_main(build)


run = main


if __name__ == "__main__":
    main()
