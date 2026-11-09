"""Indexing Worker (index-tq): chunk_markdown, embed_and_upsert, cleanup_old_chunks."""

import asyncio
import json
from datetime import UTC, datetime

from qdrant_client import models as qm
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ingest.core import keys
from ingest.core.errors import EMBED_INPUT_TOO_LONG
from ingest.core.models import (
    ChunkInput,
    ChunkResult,
    CleanupInput,
    CleanupResult,
    EmbedBatch,
    EmbedResult,
)
from ingest.core.storage import Storage
from ingest.index.chunking import chunk_markdown_text, count_tokens
from ingest.index.embedder import Embedder
from ingest.index.vectorstore import VectorStore


class IndexActivities:
    def __init__(
        self,
        storage: Storage,
        embedder: Embedder,
        vectors: VectorStore,
        embed_max_tokens: int = 8192,
    ) -> None:
        self.storage = storage
        self.embedder = embedder
        self.vectors = vectors
        self.embed_max_tokens = embed_max_tokens

    @activity.defn(name="chunk_markdown")
    async def chunk_markdown(self, inp: ChunkInput) -> ChunkResult:
        def work() -> ChunkResult:
            md = self.storage.get(keys.md_key(inp.doc_id)).decode()
            chunks = chunk_markdown_text(md, inp.chunk_tokens, inp.chunk_overlap)
            size = max(1, inp.batch_size)
            n_batches = 0
            for start in range(0, len(chunks), size):
                rows = [
                    json.dumps(
                        {
                            "chunk_index": c.chunk_index,
                            "text": c.text,
                            "heading_path": c.heading_path,
                            "page_start": c.page_start,
                            "page_end": c.page_end,
                            "content_hash": c.content_hash,
                        },
                        ensure_ascii=False,
                    )
                    for c in chunks[start : start + size]
                ]
                key = keys.chunk_batch_key(inp.doc_id, inp.index_version, n_batches)
                self.storage.put(key, ("\n".join(rows) + "\n").encode())
                n_batches += 1
            return ChunkResult(inp.doc_id, inp.index_version, n_batches, len(chunks))

        return await asyncio.to_thread(work)

    @activity.defn(name="embed_and_upsert")
    async def embed_and_upsert(self, b: EmbedBatch) -> EmbedResult:
        def work() -> EmbedResult:
            raw = self.storage.get(keys.chunk_batch_key(b.doc_id, b.index_version, b.batch_index))
            rows = [json.loads(ln) for ln in raw.decode().splitlines() if ln.strip()]
            if not rows:
                return EmbedResult(b.doc_id, b.batch_index, 0)
            for r in rows:
                if count_tokens(r["text"]) > self.embed_max_tokens:
                    raise ApplicationError(
                        f"Chunk {r['chunk_index']} vượt {self.embed_max_tokens} token",
                        type=EMBED_INPUT_TOO_LONG,
                        non_retryable=True,
                    )
            vectors = self.embedder.embed([r["text"] for r in rows])
            self.vectors.ensure_collection(self.embedder.dim, self.embedder.model)
            file_name = self._file_name(b.doc_id)
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            points = [
                qm.PointStruct(
                    id=keys.point_id(b.doc_id, b.index_version, r["chunk_index"]),
                    vector=vec,
                    payload={
                        "doc_id": b.doc_id,
                        "index_version": b.index_version,
                        "file_name": file_name,
                        "heading_path": r["heading_path"],
                        "page_start": r["page_start"],
                        "page_end": r["page_end"],
                        "chunk_index": r["chunk_index"],
                        "text": r["text"],
                        "content_hash": r["content_hash"],
                        "embedding_model": self.embedder.model,
                        "created_at": now,
                    },
                )
                for r, vec in zip(rows, vectors, strict=True)
            ]
            self.vectors.upsert(points)
            return EmbedResult(b.doc_id, b.batch_index, len(points))

        return await asyncio.to_thread(work)

    def _file_name(self, doc_id: str) -> str:
        """Tên file lấy từ front-matter của Markdown cuối (payload nhỏ, không cần truyền)."""
        import frontmatter

        md = self.storage.get(keys.md_key(doc_id)).decode()
        return str(frontmatter.loads(md).metadata.get("title", ""))

    @activity.defn(name="cleanup_old_chunks")
    async def cleanup_old_chunks(self, inp: CleanupInput) -> CleanupResult:
        def work() -> CleanupResult:
            self.vectors.ensure_collection(self.embedder.dim, self.embedder.model)
            deleted = self.vectors.delete_other_versions(inp.doc_id, inp.index_version)
            keep = f"chunks/{inp.doc_id}/v{inp.index_version}/"
            for k in self.storage.list_keys(f"chunks/{inp.doc_id}/"):
                if not k.startswith(keep):
                    self.storage.delete(k)
            return CleanupResult(inp.doc_id, deleted)

        return await asyncio.to_thread(work)
