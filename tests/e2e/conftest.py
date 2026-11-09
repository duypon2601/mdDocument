"""E2E trên stack thật (API, Temporal, Postgres, MinIO, Qdrant, Ollama).

Chạy: INGEST_E2E=1 uv run pytest tests/e2e -v
Mặc định bị bỏ qua để `uv run pytest` vẫn xanh khi offline.
"""

import os
import socket
import uuid

import pytest

from e2e.e2e_helpers import API_URL, Stack
from ingest.core.config import get_settings


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: chạy trên stack thật, cần INGEST_E2E=1")


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _skip_reason() -> str | None:
    if os.environ.get("INGEST_E2E") != "1":
        return "E2E tắt: đặt INGEST_E2E=1 để chạy"
    host, _, port = get_settings().temporal_address.partition(":")
    if not _reachable(host, int(port or 7233)):
        return f"Temporal không truy cập được tại {get_settings().temporal_address}"
    api_host, api_port = API_URL.split("//")[1].split(":")
    if not _reachable(api_host, int(api_port)):
        return f"API không truy cập được tại {API_URL}"
    return None


def pytest_collection_modifyitems(config, items):
    reason = _skip_reason()
    for item in items:
        if "tests/e2e" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)
            if reason:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def stack() -> Stack:
    return Stack()


@pytest.fixture
def tag() -> str:
    return uuid.uuid4().hex[:12]
