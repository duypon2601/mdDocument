"""index.worker: dựng embedder và Vector DB từ settings (giả lập client ngoài)."""

import sys
import types

from ingest.core.config import Settings
from ingest.index import worker


def S(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_make_embedder(monkeypatch):
    monkeypatch.setattr(worker, "OpenAICompatEmbedder", lambda *a: a)
    args = worker.make_embedder(S(embed_model="m", embed_dim=8))
    assert args == ("http://localhost:11434/v1", "none", "m", 8)


def test_make_vectors(monkeypatch):
    fake = types.ModuleType("qdrant_client")
    fake.QdrantClient = lambda url: ("qdrant", url)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake)
    monkeypatch.setattr(worker, "VectorStore", lambda client, coll: (client, coll))
    assert worker.make_vectors(S(qdrant_url="http://q:1", qdrant_collection="c")) == (
        ("qdrant", "http://q:1"),
        "c",
    )
