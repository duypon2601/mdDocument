# Adapted from rag-starter (MIT, Copyright (c) 2026 Anas Ahmad)
"""Vector DB (Qdrant), gọi qdrant-client trực tiếp, không qua wrapper langchain.

Giữ từ rag-starter: tạo collection một lần, point "dấu vân tay" embedder để phát hiện
sai kích thước vector, xóa theo filter. Khác: point id là uuid5(doc_id, version, chunk_index)
(xem keys.py), payload phẳng theo docs/c4-model.md, và không bắt buộc cùng model embedding
(re-index đổi model là use case chính), chỉ bắt buộc cùng số chiều.
Test dùng QdrantClient(":memory:").
"""

import logging

from qdrant_client import QdrantClient, models

logger = logging.getLogger(__name__)

_FINGERPRINT_POINT_ID = "00000000-0000-5000-8000-000000000001"
_FINGERPRINT_KEY = "_embedder"


class EmbedderMismatchError(RuntimeError):
    """Collection đã tạo với số chiều vector khác embedder hiện tại."""


class VectorStore:
    def __init__(self, client: QdrantClient, collection: str) -> None:
        self.client = client
        self.collection = collection

    def ensure_collection(self, dim: int, model: str = "") -> None:
        if not self.client.collection_exists(self.collection):
            try:
                self.client.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
                )
            except Exception:
                # worker khác vừa tạo xong: kiểm tra lại bên dưới
                if not self.client.collection_exists(self.collection):
                    raise
            else:
                self._store_fingerprint(dim, model)
                for field, schema in (("doc_id", "keyword"), ("index_version", "integer")):
                    self.client.create_payload_index(self.collection, field, field_schema=schema)
                logger.info("Đã tạo collection '%s'.", self.collection)
                return
        self._verify_dimension(dim)

    def _store_fingerprint(self, dim: int, model: str) -> None:
        self.client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=_FINGERPRINT_POINT_ID,
                    vector=[0.0] * dim,
                    payload={_FINGERPRINT_KEY: {"model": model, "dimensions": dim}},
                )
            ],
            wait=True,
        )

    def _verify_dimension(self, dim: int) -> None:
        vectors = self.client.get_collection(self.collection).config.params.vectors
        actual = getattr(vectors, "size", None)
        if actual is not None and actual != dim:
            raise EmbedderMismatchError(
                f"Collection '{self.collection}' có vector {actual} chiều, "
                f"embedder hiện tại cần {dim}. Tạo collection mới (INGEST_QDRANT_COLLECTION)."
            )

    def upsert(self, points: list[models.PointStruct]) -> None:
        self.client.upsert(self.collection, points=points, wait=True)

    @staticmethod
    def _doc_filter(doc_id: str, version: int | None, exclude: bool = False) -> models.Filter:
        must = [models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
        ver = (
            [models.FieldCondition(key="index_version", match=models.MatchValue(value=version))]
            if version is not None
            else []
        )
        if exclude:
            return models.Filter(must=must, must_not=ver)
        return models.Filter(must=must + ver)

    def count(self, doc_id: str, index_version: int | None = None) -> int:
        flt = self._doc_filter(doc_id, index_version)
        return self.client.count(self.collection, count_filter=flt, exact=True).count

    def delete_other_versions(self, doc_id: str, keep_version: int) -> int:
        """Xóa point của doc_id có index_version khác keep_version. Trả số point đã xóa."""
        flt = self._doc_filter(doc_id, keep_version, exclude=True)
        n = self.client.count(self.collection, count_filter=flt, exact=True).count
        if n:
            self.client.delete(
                self.collection, points_selector=models.FilterSelector(filter=flt), wait=True
            )
        return n
