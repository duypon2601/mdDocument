"""FastAPI phục vụ SPA khi có bản build, không thì giữ trang cũ ở /."""

import pytest
from fastapi.testclient import TestClient

from ingest.api.app import create_app
from ingest.core.config import Settings
from ingest.core.db import session_factory
from ingest.core.storage import MemoryStorage


def make_client(static_dir):
    app = create_app(
        MemoryStorage(),
        session_factory("sqlite:///:memory:"),
        None,
        Settings(),
        static_dir=static_dir,
    )
    return TestClient(app)


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("path", ["/", "/files", "/files/abc", "/files/abc/x", "/search", "/queues"])
def test_spa_routes_return_index(dist, path):
    r = make_client(dist).get(path)
    assert r.status_code == 200 and "<title>spa</title>" in r.text


def test_spa_assets_served(dist):
    r = make_client(dist).get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


def test_api_routes_still_work_with_spa(dist):
    c = make_client(dist)
    assert c.get("/documents").json()["total"] == 0
    assert c.get("/docs").status_code == 200


def test_fallback_to_legacy_page_without_dist(tmp_path):
    c = make_client(tmp_path / "khong-co")
    r = c.get("/")
    assert r.status_code == 200 and "<title>spa</title>" not in r.text
    assert c.get("/files").status_code == 404
