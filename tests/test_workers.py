from temporalio import activity

from ingest.convert import worker as convert
from ingest.convert.activities import ConvertActivities
from ingest.core.config import Settings
from ingest.index import worker as index
from ingest.index.activities import IndexActivities
from ingest.index.status import StatusActivities


def names(cls, methods):
    return [activity._Definition.must_from_callable(getattr(cls, m)).name for m in methods]


def test_settings_defaults_match_c4():
    s = Settings()
    assert (s.ingest_tq, s.convert_tq, s.index_tq) == ("ingest-tq", "convert-tq", "index-tq")
    assert (s.chunk_tokens, s.chunk_overlap, s.ocr_pages_per_batch) == (512, 64, 10)


def test_activity_names_match_c4_table():
    assert names(
        ConvertActivities, ["detect_format", "parse_document", "ocr_pages", "finalize_markdown"]
    ) == ["detect_format", "parse_document", "ocr_pages", "finalize_markdown"]
    assert names(IndexActivities, ["chunk_markdown", "embed_and_upsert", "cleanup_old_chunks"]) == [
        "chunk_markdown",
        "embed_and_upsert",
        "cleanup_old_chunks",
    ]
    assert names(StatusActivities, ["update_status"]) == ["update_status"]


def test_worker_entrypoints_importable():
    assert callable(convert.run) and callable(index.run)


async def test_build_worker_per_queue_registers_everything(monkeypatch):
    """Dựng Worker thật trên test server. Indexing Worker trông cả ingest-tq và index-tq."""
    from qdrant_client import QdrantClient
    from temporalio.testing import WorkflowEnvironment

    from ingest.convert.ocr import FakeOcr
    from ingest.core.db import DocumentRepository, make_engine
    from ingest.core.storage import MemoryStorage
    from ingest.index.embedder import FakeEmbedder
    from ingest.index.vectorstore import VectorStore

    repo = DocumentRepository(make_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    monkeypatch.setattr(index, "make_repo", lambda s: repo)
    monkeypatch.setattr(convert, "make_storage", lambda s: MemoryStorage())
    monkeypatch.setattr(convert, "make_ocr", lambda s=None: FakeOcr())
    monkeypatch.setattr(index, "make_storage", lambda s: MemoryStorage())
    monkeypatch.setattr(index, "make_embedder", lambda s: FakeEmbedder())
    monkeypatch.setattr(
        index, "make_vectors", lambda s: VectorStore(QdrantClient(":memory:"), "docs")
    )
    s = Settings()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        assert (await convert.build(s, env.client)).task_queue == s.convert_tq
        workers = await index.build(s, env.client)
        assert [w.task_queue for w in workers] == [s.ingest_tq, s.index_tq]


async def test_run_worker_chay_nhieu_worker_cung_luc():
    from ingest.core.runtime import run_worker

    ran = []

    class W:
        def __init__(self, name):
            self.name = name

        async def run(self):
            ran.append(self.name)

    await run_worker([W("ingest"), W("index")])
    await run_worker(W("convert"))
    assert ran == ["ingest", "index", "convert"]
