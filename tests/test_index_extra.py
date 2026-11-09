"""Bổ sung cho chunking, embed, cleanup, embedder HTTP."""

import hashlib
import json

import httpx
import pytest
from qdrant_client import QdrantClient
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from ingest.core import keys
from ingest.core.models import ChunkInput, CleanupInput, EmbedBatch
from ingest.core.storage import MemoryStorage
from ingest.index.activities import IndexActivities
from ingest.index.chunking import chunk_markdown_text, count_tokens
from ingest.index.embedder import FakeEmbedder, OpenAICompatEmbedder
from ingest.index.vectorstore import VectorStore

ENV = ActivityEnvironment

VI = (
    "Bên A có nghĩa vụ thanh toán đầy đủ cho Bên B trong thời hạn ba mươi ngày kể từ ngày "
    "nhận được hóa đơn hợp lệ. Mọi khoản chậm trả sẽ chịu lãi suất theo quy định của pháp luật. "
)


def fm(body: str) -> str:
    return f"---\ndoc_id: d1\ntitle: t.pdf\n---\n\n{body}"


def make(md: str | None = None, doc="d1"):
    st = MemoryStorage()
    st.put(keys.md_key(doc), (md if md is not None else fm("Xin chào")).encode())
    vs = VectorStore(QdrantClient(":memory:"), "docs")
    return st, vs, IndexActivities(st, FakeEmbedder(), vs)


# ---------- chunking ----------


def test_default_limits_512_64_respected_on_long_vietnamese_text():
    chunks = chunk_markdown_text(fm("<!-- page: 1 -->\n\n" + VI * 120))  # mặc định 512/64
    assert len(chunks) > 3
    assert all(count_tokens(c.text) <= 512 for c in chunks)
    assert max(count_tokens(c.text) for c in chunks) > 400  # thật sự lấp đầy, không băm nhỏ


def test_overlap_shares_text_between_consecutive_chunks():
    chunks = chunk_markdown_text(fm("<!-- page: 1 -->\n\n" + VI * 60), 128, 32)
    assert len(chunks) > 2
    shared = [
        set(chunks[i].text.split()) & set(chunks[i + 1].text.split())
        for i in range(len(chunks) - 1)
    ]
    assert all(len(s) > 3 for s in shared)


def test_vietnamese_diacritics_preserved_and_hash_matches_text():
    chunks = chunk_markdown_text(fm("<!-- page: 1 -->\n\nĐiều khoản thanh toán: ươ ạ ỹ"))
    assert chunks[0].text == "Điều khoản thanh toán: ươ ạ ỹ"
    assert chunks[0].content_hash == "sha256:" + hashlib.sha256(chunks[0].text.encode()).hexdigest()


def test_three_level_heading_path_and_reset_on_new_h1():
    md = fm(
        "<!-- page: 1 -->\n\n# Điều 3\n\nA\n\n## Thanh toán\n\nB\n\n### Phạt\n\nC\n\n# Điều 4\n\nD"
    )
    by_text = {c.text.split("\n")[-1]: c.heading_path for c in chunk_markdown_text(md)}
    assert by_text["A"] == "Điều 3"
    assert by_text["B"] == "Điều 3 > Thanh toán"
    assert by_text["C"] == "Điều 3 > Thanh toán > Phạt"
    assert by_text["D"] == "Điều 4"


def test_heading_path_carries_over_to_next_page_without_heading():
    md = fm("<!-- page: 1 -->\n\n# Điều 3\n\nPhần đầu.\n\n<!-- page: 2 -->\n\nPhần nối tiếp.")
    chunks = chunk_markdown_text(md)
    last = chunks[-1]
    assert last.page_start == 2 and "nối tiếp" in last.text
    assert last.heading_path == "Điều 3"


def test_page_start_equals_page_end_and_follow_markers():
    md = fm("<!-- page: 3 -->\n\nBa\n\n<!-- page: 7 -->\n\nBảy")
    pages = [(c.page_start, c.page_end) for c in chunk_markdown_text(md)]
    assert pages == [(3, 3), (7, 7)]


def test_text_without_markers_defaults_to_page_one():
    chunks = chunk_markdown_text(fm("# Tiêu đề\n\nNội dung docx"))
    assert chunks and all(c.page_start == 1 for c in chunks)


def test_frontmatter_is_not_chunked():
    chunks = chunk_markdown_text(fm("<!-- page: 1 -->\n\nNội dung"))
    assert all("doc_id" not in c.text and "title:" not in c.text for c in chunks)


@pytest.mark.parametrize("md", ["", fm(""), fm("   \n\n"), fm("<!-- page: 1 -->\n\n  ")])
def test_empty_documents_yield_no_chunks(md):
    assert chunk_markdown_text(md) == []


def test_large_table_is_not_split():
    rows = "\n".join(f"| {i} | giá trị dòng {i} |" for i in range(300))
    md = fm(f"<!-- page: 1 -->\n\nĐầu bảng\n\n| a | b |\n|---|---|\n{rows}\n\nCuối")
    tables = [c for c in chunk_markdown_text(md, 128, 16) if c.text.startswith("| a | b |")]
    assert len(tables) == 1 and tables[0].text.count("\n") >= 300


def test_chunk_index_dense_and_deterministic_across_pages():
    md = fm("".join(f"<!-- page: {p} -->\n\n# H{p}\n\n{VI * 20}\n\n" for p in range(1, 5)))
    a, b = chunk_markdown_text(md, 128, 16), chunk_markdown_text(md, 128, 16)
    assert a == b and [c.chunk_index for c in a] == list(range(len(a)))
    assert [c.page_start for c in a] == sorted(c.page_start for c in a)


def test_non_alnum_table_is_skipped():
    md = fm("<!-- page: 1 -->\n\n|---|---|\n| | |\n\nThật")
    chunks = chunk_markdown_text(md)
    assert [c.text for c in chunks] == ["Thật"]


# ---------- chunk_markdown activity ----------


async def test_chunk_batch_size_zero_is_treated_as_one():
    st, _, acts = make(fm("<!-- page: 1 -->\n\nA\n\n<!-- page: 2 -->\n\nB"))
    r = await ENV().run(acts.chunk_markdown, ChunkInput("d1", "x", 1, 128, 16, 0))
    assert r.batch_count == r.chunk_count == 2


async def test_chunk_batches_are_jsonl_with_required_fields_and_dense_indices():
    st, _, acts = make(fm("<!-- page: 1 -->\n\n" + VI * 40))
    r = await ENV().run(acts.chunk_markdown, ChunkInput("d1", "x", 4, 128, 16, 3))
    rows = []
    for i in range(r.batch_count):
        raw = st.get(keys.chunk_batch_key("d1", 4, i)).decode()
        assert raw.endswith("\n")
        rows += [json.loads(line) for line in raw.splitlines()]
    assert [x["chunk_index"] for x in rows] == list(range(r.chunk_count))
    assert set(rows[0]) == {
        "chunk_index", "text", "heading_path", "page_start", "page_end", "content_hash",
    }  # fmt: skip


async def test_chunk_missing_markdown_is_retryable_error():
    st, _, acts = make()
    st.delete(keys.md_key("d1"))
    with pytest.raises(FileNotFoundError):
        await ENV().run(acts.chunk_markdown, ChunkInput("d1"))


# ---------- embed_and_upsert ----------


async def prepare(acts, doc="d1", version=1, batch=2):
    r = await ENV().run(acts.chunk_markdown, ChunkInput(doc, "x", version, 128, 16, batch))
    for i in range(r.batch_count):
        await ENV().run(acts.embed_and_upsert, EmbedBatch(doc, version, i))
    return r


async def test_point_ids_are_uuid5_of_doc_version_chunk_and_stable_on_rerun():
    st, vs, acts = make(fm("<!-- page: 1 -->\n\n" + VI * 30))
    r = await prepare(acts)
    ids1 = sorted(str(p.id) for p in vs.client.scroll("docs", limit=500)[0] if "text" in p.payload)
    await prepare(acts)
    ids2 = sorted(str(p.id) for p in vs.client.scroll("docs", limit=500)[0] if "text" in p.payload)
    assert ids1 == ids2 == sorted(keys.point_id("d1", 1, i) for i in range(r.chunk_count))


async def test_rerun_of_one_batch_keeps_vector_and_payload_identical_except_timestamp():
    st, vs, acts = make(fm("<!-- page: 1 -->\n\n" + VI * 10))
    await prepare(acts, batch=100)
    pid = keys.point_id("d1", 1, 0)
    before = vs.client.retrieve("docs", [pid], with_vectors=True)[0]
    await ENV().run(acts.embed_and_upsert, EmbedBatch("d1", 1, 0))
    after = vs.client.retrieve("docs", [pid], with_vectors=True)[0]
    assert after.vector == pytest.approx(before.vector, abs=1e-6)
    strip = lambda p: {k: v for k, v in p.items() if k != "created_at"}  # noqa: E731
    assert strip(before.payload) == strip(after.payload)


async def test_versions_do_not_collide_in_same_collection():
    st, vs, acts = make(fm("<!-- page: 1 -->\n\n" + VI * 5))
    await prepare(acts, version=1)
    await prepare(acts, version=2)
    assert vs.count("d1", 1) == vs.count("d1", 2) > 0


async def test_empty_batch_file_upserts_nothing_and_does_not_call_embedder():
    st, vs, acts = make()
    st.put(keys.chunk_batch_key("d1", 1, 0), b"\n")
    res = await ENV().run(acts.embed_and_upsert, EmbedBatch("d1", 1, 0))
    assert res.upserted == 0 and acts.embedder.calls == 0


async def test_embed_missing_batch_is_retryable_infrastructure_error():
    _, _, acts = make()
    with pytest.raises(FileNotFoundError):
        await ENV().run(acts.embed_and_upsert, EmbedBatch("d1", 1, 9))


async def test_embed_too_long_checks_every_row_and_writes_nothing():
    st, vs, _ = make(fm("<!-- page: 1 -->\n\nngắn\n\n<!-- page: 2 -->\n\n" + VI * 20))
    acts = IndexActivities(st, FakeEmbedder(), vs, embed_max_tokens=60)
    await ENV().run(acts.chunk_markdown, ChunkInput("d1", "x", 1, 128, 16, 50))
    with pytest.raises(ApplicationError) as ei:
        await ENV().run(acts.embed_and_upsert, EmbedBatch("d1", 1, 0))
    assert ei.value.type == "EMBED_INPUT_TOO_LONG" and ei.value.non_retryable
    assert acts.embedder.calls == 0  # không tốn call embedding
    assert not vs.client.collection_exists("docs") or vs.count("d1", 1) == 0


# ---------- cleanup ----------


async def test_cleanup_keeps_new_version_deletes_every_older_one():
    st, vs, acts = make(fm("<!-- page: 1 -->\n\n" + VI * 5))
    for v in (1, 2, 3):
        await prepare(acts, version=v)
    n3, n_old = vs.count("d1", 3), vs.count("d1", 1) + vs.count("d1", 2)
    res = await ENV().run(acts.cleanup_old_chunks, CleanupInput("d1", 3))
    assert res.deleted == n_old > 0
    assert vs.count("d1", 1) == vs.count("d1", 2) == 0 and vs.count("d1", 3) == n3 > 0
    assert all("/v3/" in k for k in st.list_keys("chunks/d1/"))


async def test_cleanup_does_not_touch_doc_with_prefix_overlap():
    st, vs, acts = make(fm("<!-- page: 1 -->\n\n" + VI * 5))
    st.put(keys.md_key("d10"), fm("<!-- page: 1 -->\n\nKhác").encode())
    await prepare(acts, doc="d1", version=1)
    await prepare(acts, doc="d10", version=1)
    await ENV().run(acts.cleanup_old_chunks, CleanupInput("d1", 2))  # xóa mọi thứ không phải v2
    assert vs.count("d10", 1) > 0 and st.list_keys("chunks/d10/")


async def test_cleanup_is_idempotent_and_ignores_fingerprint_point():
    st, vs, acts = make(fm("<!-- page: 1 -->\n\nA"))
    await prepare(acts, version=1)
    for _ in range(2):
        await ENV().run(acts.cleanup_old_chunks, CleanupInput("d1", 1))
    assert vs.count("d1", 1) == 1
    assert vs.client.count("docs", exact=True).count == 2  # chunk + dấu vân tay embedder


# ---------- OpenAICompatEmbedder (mock ở biên mạng) ----------


def embedder_with(handler) -> OpenAICompatEmbedder:
    e = OpenAICompatEmbedder("http://emb/v1", "k", "m", 2)
    e._client = httpx.Client(
        base_url="http://emb/v1", transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer k"},
    )  # fmt: skip
    return e


def test_embedder_restores_input_order_by_index_and_sends_auth():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [2.0, 2.0]}, {"index": 0, "embedding": [1.0, 1.0]},
        ]})  # fmt: skip

    out = embedder_with(handler).embed(["a", "b"])
    assert out == [[1.0, 1.0], [2.0, 2.0]]
    assert seen["auth"] == "Bearer k" and seen["body"] == {"model": "m", "input": ["a", "b"]}


def test_embedder_400_token_limit_is_non_retryable():
    e = embedder_with(lambda r: httpx.Response(400, text="maximum context length: too many tokens"))
    with pytest.raises(ApplicationError) as ei:
        e.embed(["x"])
    assert ei.value.type == "EMBED_INPUT_TOO_LONG" and ei.value.non_retryable


@pytest.mark.parametrize("status", [429, 500, 503])
def test_embedder_429_and_5xx_raise_plain_error_so_temporal_retries(status):
    e = embedder_with(lambda r: httpx.Response(status, text="slow down"))
    with pytest.raises(httpx.HTTPStatusError) as ei:
        e.embed(["x"])
    assert not isinstance(ei.value, ApplicationError)


def test_embedder_400_without_token_hint_is_not_misclassified():
    e = embedder_with(lambda r: httpx.Response(400, text="bad api key format"))
    with pytest.raises(httpx.HTTPStatusError):
        e.embed(["x"])
