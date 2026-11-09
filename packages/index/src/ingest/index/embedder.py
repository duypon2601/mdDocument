"""Embedding client: API tương thích OpenAI hoặc FakeEmbedder (test)."""

import hashlib
import re
from typing import Protocol

import httpx
from temporalio.exceptions import ApplicationError

from ingest.core.errors import EMBED_INPUT_TOO_LONG


class Embedder(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Vector xác định từ hash nội dung, cùng text luôn ra cùng vector."""

    def __init__(self, dim: int = 16, model: str = "fake-embed") -> None:
        self.dim = dim
        self.model = model
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([(h[i % len(h)] / 255.0) * 2 - 1 for i in range(self.dim)])
        return out


# Thông báo "quá dài" của OpenAI, Ollama, vLLM, TEI. Không xét chữ "token" trơn: lỗi
# kết nối nội bộ của Ollama ("Post .../tokenize: connection reset") cũng chứa chữ đó
# nhưng là lỗi tạm thời, phải để Temporal thử lại.
_TOO_LONG = re.compile(
    r"too long|exceed|maximum context|context length|max(imum)?[ _]?(input|sequence)?[ _]?tokens"
    r"|input length",
    re.I,
)
_TRANSIENT = re.compile(r"connection (reset|refused)|dial tcp|EOF|timeout", re.I)


def _is_too_long(body: str) -> bool:
    return bool(_TOO_LONG.search(body)) and not _TRANSIENT.search(body)


class OpenAICompatEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, dim: int, timeout: float = 90):
        self.model = model
        self.dim = dim
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.post("/embeddings", json={"model": self.model, "input": texts})
        if resp.status_code == 400 and _is_too_long(resp.text):
            raise ApplicationError(
                f"Input quá dài cho model: {resp.text[:200]}",
                type=EMBED_INPUT_TOO_LONG,
                non_retryable=True,
            )
        # 429 và 5xx: raise để Temporal retry theo RETRY_EMBED (backoff tối đa 5 phút)
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]
