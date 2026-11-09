import httpx
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models

from ingest.api.app import create_app
from ingest.api.search import QdrantSearcher, SearchUnavailable
from ingest.core import keys
from ingest.core.db import session_factory
from ingest.core.storage import MemoryStorage

FINGERPRINT_ID = "00000000-0000-5000-8000-000000000001"
VECS = {"alpha": [1.0, 0.0, 0.0], "beta": [0.0, 1.0, 0.0], "mix": [0.95, 0.1, 0.0]}


def embed_transport(fail: bool = False) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(500, text="boom")
        import json

        body = json.loads(req.content)
        vec = VECS[body["input"][0]]
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vec}]})

    return httpx.MockTransport(handler)


def point(doc_id: str, idx: int, vec: list[float], text: str) -> models.PointStruct:
    return models.PointStruct(
        id=keys.point_id(doc_id, 1, idx),
        vector=vec,
        payload={
            "doc_id": doc_id,
            "index_version": 1,
            "file_name": f"{doc_id}.pdf",
            "heading_path": "Mục 1",
            "page_start": 1,
            "page_end": 2,
            "chunk_index": idx,
            "text": text,
            "content_hash": "h",
            "embedding_model": "m",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )


@pytest.fixture
def qdrant() -> QdrantClient:
    c = QdrantClient(":memory:")
    c.create_collection("documents", vectors_config=models.VectorParams(size=3, distance="Cosine"))
    c.upsert(
        "documents",
        points=[
            models.PointStruct(
                id=FINGERPRINT_ID, vector=[1.0, 0.0, 0.0], payload={"_embedder": {"model": "m"}}
            ),
            point("d1", 0, [1.0, 0.0, 0.0], "gần alpha"),
            point("d1", 1, [0.7, 0.7, 0.0], "giữa"),
            point("d2", 0, [0.0, 1.0, 0.0], "gần beta"),
        ],
    )
    return c


def make_searcher(qdrant: QdrantClient, fail: bool = False, collection="documents"):
    http = httpx.Client(base_url="http://embed/v1", transport=embed_transport(fail))
    return QdrantSearcher(qdrant, collection, "http://embed/v1", "k", "test-model", http)


def test_search_orders_by_score_and_skips_fingerprint(qdrant):
    out = make_searcher(qdrant).search("alpha", 8, None)
    assert out["query"] == "alpha"
    assert out["model"] == "test-model"
    res = out["results"]
    assert [r["text"] for r in res] == ["gần alpha", "giữa", "gần beta"]
    assert res[0]["score"] > res[1]["score"] > res[2]["score"]
    assert set(res[0]) == {
        "score",
        "doc_id",
        "file_name",
        "index_version",
        "chunk_index",
        "heading_path",
        "page_start",
        "page_end",
        "text",
    }


def test_search_top_k_and_doc_filter(qdrant):
    s = make_searcher(qdrant)
    assert len(s.search("alpha", 1, None)["results"]) == 1
    res = s.search("alpha", 8, "d2")["results"]
    assert [r["doc_id"] for r in res] == ["d2"]


def test_search_missing_collection_is_empty(qdrant):
    out = make_searcher(qdrant, collection="chua-co").search("alpha", 8, None)
    assert out["results"] == []


def test_search_embed_failure_raises_unavailable(qdrant):
    with pytest.raises(SearchUnavailable):
        make_searcher(qdrant, fail=True).search("alpha", 8, None)


@pytest.fixture
def client(qdrant):
    app = create_app(
        MemoryStorage(), session_factory("sqlite:///:memory:"), None, searcher=make_searcher(qdrant)
    )
    return TestClient(app)


def test_post_search_ok(client):
    r = client.post("/search", json={"query": "mix", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2
    assert body["results"][0]["text"] == "gần alpha"


def test_post_search_doc_filter(client):
    r = client.post("/search", json={"query": "alpha", "doc_id": "d2"})
    assert [x["doc_id"] for x in r.json()["results"]] == ["d2"]


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "x" * 2001},
        {"query": "alpha", "top_k": 51},
        {"query": "alpha", "top_k": 0},
    ],
)
def test_post_search_validation(client, body):
    assert client.post("/search", json=body).status_code == 422


def test_post_search_503_without_searcher():
    app = create_app(MemoryStorage(), session_factory("sqlite:///:memory:"), None)
    r = TestClient(app).post("/search", json={"query": "alpha"})
    assert r.status_code == 503
    assert r.json()["code"] == "SEARCH_UNAVAILABLE"


def test_post_search_503_when_embedder_fails(qdrant):
    app = create_app(
        MemoryStorage(),
        session_factory("sqlite:///:memory:"),
        None,
        searcher=make_searcher(qdrant, fail=True),
    )
    r = TestClient(app).post("/search", json={"query": "alpha"})
    assert r.status_code == 503
    assert r.json()["code"] == "SEARCH_UNAVAILABLE"
    assert r.json()["detail"]
