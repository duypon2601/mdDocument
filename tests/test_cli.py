"""CLI `ingest`: gọi API qua httpx (giả lập), worker và api (giả lập import)."""

import json
import sys
import types

import httpx
import pytest
from typer.testing import CliRunner

from ingest import cli

runner = CliRunner()
BASE = "http://api.test"


@pytest.fixture
def calls(monkeypatch):
    """Thay httpx.request bằng hàm ghi lại lời gọi và trả response đặt sẵn."""
    rec: dict = {"calls": [], "response": httpx.Response(200, json={"ok": True})}

    def fake_request(method, url, **kw):
        rec["calls"].append((method, url, kw))
        resp = rec["response"]
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(cli.httpx, "request", fake_request)
    return rec


def run(*args):
    return runner.invoke(cli.app, [*args, "--api-url", BASE + "/"])


def test_upload_one_file(calls, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4")
    r = run("upload", str(f))
    assert r.exit_code == 0, r.output
    method, url, kw = calls["calls"][0]
    assert (method, url) == ("POST", f"{BASE}/documents")
    assert kw["files"] == {"file": ("a.pdf", b"%PDF-1.4")}
    assert json.loads(r.output) == {"ok": True}


def test_upload_many_files_uses_batch(calls, tmp_path):
    paths = []
    for name in ("a.txt", "b.txt"):
        p = tmp_path / name
        p.write_text(name)
        paths.append(str(p))
    r = run("upload", *paths)
    assert r.exit_code == 0, r.output
    method, url, kw = calls["calls"][0]
    assert url == f"{BASE}/documents/batch"
    assert [name for _, (name, _) in kw["files"]] == ["a.txt", "b.txt"]


def test_upload_missing_file_rejected(calls, tmp_path):
    r = run("upload", str(tmp_path / "khong-co.pdf"))
    assert r.exit_code != 0
    assert calls["calls"] == []


def test_status(calls):
    calls["response"] = httpx.Response(200, json={"doc_id": "abc", "status": "INDEXED"})
    r = run("status", "abc")
    assert r.exit_code == 0
    assert calls["calls"][0][:2] == ("GET", f"{BASE}/documents/abc")
    assert '"INDEXED"' in r.output


def test_list_with_filters(calls):
    calls["response"] = httpx.Response(
        200,
        json={
            "items": [
                {
                    "doc_id": "0123456789abcdef",
                    "status": "INDEXED",
                    "chunk_count": 7,
                    "file_name": "hợp đồng.pdf",
                }
            ],
            "total": 3,
        },
    )
    r = run("list", "--status", "INDEXED", "--q", "hợp", "--limit", "5", "--offset", "1")
    assert r.exit_code == 0, r.output
    _, url, kw = calls["calls"][0]
    assert url == f"{BASE}/documents"
    assert kw["params"] == {"limit": 5, "offset": 1, "status": "INDEXED", "q": "hợp"}
    assert "0123456789ab" in r.output and "hợp đồng.pdf" in r.output
    assert "(1/3)" in r.output


def test_list_without_filters_sends_only_paging(calls):
    calls["response"] = httpx.Response(200, json={"items": [], "total": 0})
    r = run("list")
    assert r.exit_code == 0
    assert calls["calls"][0][2]["params"] == {"limit": 20, "offset": 0}
    assert "(0/0)" in r.output


@pytest.mark.parametrize(
    ("args", "url", "params"),
    [
        (("review", "d1", "approve"), "/documents/d1/review", {"decision": "approve"}),
        (("reindex", "d1"), "/documents/d1/reindex", None),
        (("cancel", "d1"), "/documents/d1/cancel", None),
    ],
)
def test_post_commands(calls, args, url, params):
    r = run(*args)
    assert r.exit_code == 0, r.output
    method, called_url, kw = calls["calls"][0]
    assert (method, called_url) == ("POST", BASE + url)
    assert kw.get("params") == params


def test_http_error_status_exits_1(calls):
    calls["response"] = httpx.Response(404, text="không thấy")
    r = run("status", "x")
    assert r.exit_code == 1
    assert "Lỗi 404" in r.output


def test_connection_error_exits_2(calls):
    calls["response"] = httpx.ConnectError("refused")
    r = run("status", "x")
    assert r.exit_code == 2
    assert "Không gọi được API" in r.output


def test_base_url_falls_back_to_default():
    assert cli._base(None) == "http://localhost:8000"
    assert cli._base("http://x/") == "http://x"


def test_api_command_runs_uvicorn(monkeypatch):
    seen = {}
    fake = types.ModuleType("uvicorn")
    fake.run = lambda target, **kw: seen.update(target=target, **kw)
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    r = runner.invoke(cli.app, ["api", "--port", "9001", "--reload"])
    assert r.exit_code == 0, r.output
    assert seen == {
        "target": "ingest.api.app:create_default_app",
        "factory": True,
        "host": "0.0.0.0",  # noqa: S104
        "port": 9001,
        "reload": True,
    }


@pytest.mark.parametrize("name", ["convert", "index"])
def test_worker_commands_call_main(monkeypatch, name):
    import importlib

    mod = importlib.import_module(f"ingest.{name}.worker")
    called = []
    monkeypatch.setattr(mod, "main", lambda: called.append(name))
    r = runner.invoke(cli.app, ["worker", name])
    assert r.exit_code == 0, r.output
    assert called == [name]


def test_missing_package_exits_2(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda m: None if m == "ingest.convert" else real(m)
    )
    r = runner.invoke(cli.app, ["worker", "convert"])
    assert r.exit_code == 2
    assert "ingest-convert" in r.output
