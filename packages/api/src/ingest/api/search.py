"""Tìm kiếm ngữ nghĩa thử: embed câu hỏi rồi truy vấn Qdrant.

Package api không được import ingest.index, nên client embedding và hằng số dấu vân tay
được viết lại gọn ở đây.
"""

from typing import Protocol

import httpx
from qdrant_client import QdrantClient, models

# Trùng với ingest.index.vectorstore: point lưu thông tin embedder, không phải chunk.
_FINGERPRINT_POINT_ID = "00000000-0000-5000-8000-000000000001"


class SearchUnavailable(RuntimeError):
    """Embedder hoặc Qdrant không dùng được."""


class Searcher(Protocol):
    def search(self, query: str, top_k: int, doc_id: str | None) -> dict: ...


class QdrantSearcher:
    def __init__(
        self,
        client: QdrantClient,
        collection: str,
        embed_base_url: str,
        embed_api_key: str,
        embed_model: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._client = client
        self._collection = collection
        self._model = embed_model
        self._http = http_client or httpx.Client(
            base_url=embed_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {embed_api_key}"},
            timeout=30,
        )

    def _embed(self, text: str) -> list[float]:
        try:
            resp = self._http.post("/embeddings", json={"model": self._model, "input": [text]})
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise SearchUnavailable(f"Không gọi được endpoint embedding: {exc}") from exc

    def search(self, query: str, top_k: int, doc_id: str | None) -> dict:
        vec = self._embed(query)
        must = (
            [models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
            if doc_id
            else None
        )
        flt = models.Filter(
            must=must, must_not=[models.HasIdCondition(has_id=[_FINGERPRINT_POINT_ID])]
        )
        try:
            if not self._client.collection_exists(self._collection):
                return {"query": query, "model": self._model, "results": []}
            res = self._client.query_points(
                self._collection, query=vec, limit=top_k, query_filter=flt, with_payload=True
            )
        except Exception as exc:
            raise SearchUnavailable(f"Không truy vấn được Qdrant: {exc}") from exc
        results = []
        for p in res.points:
            pl = p.payload or {}
            results.append(
                {
                    "score": p.score,
                    "doc_id": pl.get("doc_id"),
                    "file_name": pl.get("file_name"),
                    "index_version": pl.get("index_version"),
                    "chunk_index": pl.get("chunk_index"),
                    "heading_path": pl.get("heading_path"),
                    "page_start": pl.get("page_start"),
                    "page_end": pl.get("page_end"),
                    "text": pl.get("text"),
                }
            )
        return {"query": query, "model": self._model, "results": results}
