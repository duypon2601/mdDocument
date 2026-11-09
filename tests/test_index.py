import json
from dataclasses import asdict

import pytest
from qdrant_client import QdrantClient
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from ingest.core import keys
from ingest.core.models import ChunkInput, CleanupInput, EmbedBatch
from ingest.core.storage import MemoryStorage
from ingest.index.activities import IndexActivities
from ingest.index.chunking import chunk_markdown_text, count_tokens
from ingest.index.embedder import FakeEmbedder
from ingest.index.vectorstore import EmbedderMismatchError, VectorStore

MD = (
    """---
doc_id: d1
title: hop-dong.pdf
---

<!-- page: 1 -->

# Điều 3

## Thanh toán

Bên A thanh toán trong 30 ngày. """
    + "Nội dung dài. " * 400
    + """

<!-- page: 2 -->

Tiếp theo trang hai.

| a | b |
|---|---|
| 1 | 2 |
"""
)


def make(embedder=None):
    st = MemoryStorage()
    st.put(keys.md_key("d1"), MD.encode())
    vs = VectorStore(QdrantClient(":memory:"), "docs")
    emb = embedder or FakeEmbedder()
    return st, vs, IndexActivities(st, emb, vs)


def test_chunker_heading_path_pages_table_and_size():
    chunks = chunk_markdown_text(MD, 128, 16)
    assert len(chunks) > 3
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].heading_path == "Điều 3 > Thanh toán"
    assert chunks[0].page_start == 1
    assert any(c.page_start == 2 for c in chunks)
    assert all("page:" not in c.text for c in chunks)
    assert any(c.text.startswith("| a | b |") for c in chunks)
    assert all(count_tokens(c.text) <= 128 + 20 for c in chunks if "|" not in c.text)
    assert chunk_markdown_text(MD, 128, 16) == chunks  # xác định


async def test_chunk_and_embed_idempotent_and_payload():
    st, vs, acts = make()
    env = ActivityEnvironment()
    cr = await env.run(acts.chunk_markdown, ChunkInput("d1", "x", 1, 128, 16, 5))
    assert cr.batch_count == -(-cr.chunk_count // 5) and cr.chunk_count > 5
    assert st.exists(keys.chunk_batch_key("d1", 1, cr.batch_count - 1))
    cr2 = await env.run(acts.chunk_markdown, ChunkInput("d1", "x", 1, 128, 16, 5))
    assert cr2 == cr
    for _ in range(2):  # chạy lại không sinh bản trùng
        for i in range(cr.batch_count):
            r = await env.run(acts.embed_and_upsert, EmbedBatch("d1", 1, i))
            assert json.loads(json.dumps(asdict(r)))["batch_index"] == i
        assert vs.count("d1", 1) == cr.chunk_count
    pts, _ = vs.client.scroll("docs", limit=1000, with_payload=True)
    p = next(x.payload for x in pts if x.payload.get("doc_id") == "d1")
    assert set(p) == {
        "doc_id", "index_version", "file_name", "heading_path", "page_start", "page_end",
        "chunk_index", "text", "content_hash", "embedding_model", "created_at",
    }  # fmt: skip
    assert p["file_name"] == "hop-dong.pdf" and p["embedding_model"] == "fake-embed"
    assert p["content_hash"].startswith("sha256:") and p["created_at"].endswith("Z")
    ids = {str(x.id) for x in pts if x.payload.get("doc_id") == "d1"}
    assert keys.point_id("d1", 1, 0) in ids


async def test_cleanup_removes_only_old_version():
    st, vs, acts = make()
    env = ActivityEnvironment()
    for v in (1, 2):
        cr = await env.run(acts.chunk_markdown, ChunkInput("d1", "x", v, 128, 16, 50))
        for i in range(cr.batch_count):
            await env.run(acts.embed_and_upsert, EmbedBatch("d1", v, i))
    # doc khác không bị đụng
    st.put(keys.md_key("d2"), MD.encode())
    cr = await env.run(acts.chunk_markdown, ChunkInput("d2", "x", 1, 128, 16, 50))
    for i in range(cr.batch_count):
        await env.run(acts.embed_and_upsert, EmbedBatch("d2", 1, i))
    n1, n2 = vs.count("d1", 1), vs.count("d1", 2)
    assert n1 and n2
    res = await env.run(acts.cleanup_old_chunks, CleanupInput("d1", 2))
    assert res.deleted == n1
    assert vs.count("d1", 1) == 0 and vs.count("d1", 2) == n2 and vs.count("d2", 1) > 0
    assert st.list_keys("chunks/d1/") and all("/v2/" in k for k in st.list_keys("chunks/d1/"))
    assert (await env.run(acts.cleanup_old_chunks, CleanupInput("d1", 2))).deleted == 0


async def test_embed_input_too_long_non_retryable():
    st, vs, _ = make()
    acts = IndexActivities(st, FakeEmbedder(), vs, embed_max_tokens=5)
    env = ActivityEnvironment()
    await env.run(acts.chunk_markdown, ChunkInput("d1", "x", 1, 128, 16, 50))
    with pytest.raises(ApplicationError) as ei:
        await env.run(acts.embed_and_upsert, EmbedBatch("d1", 1, 0))
    assert ei.value.type == "EMBED_INPUT_TOO_LONG" and ei.value.non_retryable


def test_dimension_mismatch_detected():
    vs = VectorStore(QdrantClient(":memory:"), "docs")
    vs.ensure_collection(8, "m1")
    vs.ensure_collection(8, "m2")  # đổi model cùng số chiều: được (re-index)
    with pytest.raises(EmbedderMismatchError):
        vs.ensure_collection(16, "m3")


def test_fake_embedder_deterministic():
    e = FakeEmbedder()
    assert e.embed(["a", "b"]) == e.embed(["a", "b"]) and e.embed(["a"])[0] != e.embed(["b"])[0]
