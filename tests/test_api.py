import pytest
from fastapi.testclient import TestClient

from conftest import make_pdf
from ingest.api.app import create_app
from ingest.api.dedup import compute_doc_id
from ingest.api.validator import detect_mime, validate_upload
from ingest.core import keys
from ingest.core.config import Settings
from ingest.core.db import session_factory
from ingest.core.storage import MemoryStorage


class FakeWf:
    def __init__(self) -> None:
        self.ingests, self.reindexes, self.reviews, self.cancels = [], [], [], []
        self.progress = "CONVERTING"
        self.progress_ids, self.cancel_ids = [], []

    async def start_ingest(self, inp):
        self.ingests.append(inp)

    async def start_reindex(self, inp):
        self.reindexes.append(inp)

    async def get_progress(self, doc_id, workflow_id=None):
        self.progress_ids.append(workflow_id)
        return self.progress

    async def review_decision(self, doc_id, decision):
        self.reviews.append((doc_id, decision))

    async def cancel(self, doc_id, workflow_id=None):
        self.cancels.append(doc_id)
        self.cancel_ids.append(workflow_id)


@pytest.fixture
def env():
    storage, repo, wf = MemoryStorage(), session_factory("sqlite:///:memory:"), FakeWf()
    settings = Settings(max_upload_bytes=10_000)
    client = TestClient(create_app(storage, repo, wf, settings))
    return client, storage, repo, wf


def up(client, name="a.pdf", data=None, **kw):
    data = data if data is not None else make_pdf(["xin chào"])
    return client.post("/documents", files={"file": (name, data)}, **kw)


def test_upload_stores_raw_and_starts_workflow(env):
    client, storage, repo, wf = env
    data = make_pdf(["hello"])
    r = up(client, "a.pdf", data)
    assert r.status_code == 202
    body = r.json()
    doc_id = compute_doc_id(data)
    assert body["doc_id"] == doc_id and body["duplicate"] is False
    assert body["status"] == "RECEIVED" and body["mime"] == "application/pdf"
    assert storage.get(keys.raw_key(doc_id, "a.pdf")) == data
    assert repo.get(doc_id) is not None
    assert len(wf.ingests) == 1
    assert wf.ingests[0].raw_key == keys.raw_key(doc_id, "a.pdf")


def test_duplicate_upload_returns_existing_without_new_workflow(env):
    client, _, _, wf = env
    data = make_pdf(["same"])
    first = up(client, "a.pdf", data).json()
    r = up(client, "other-name.pdf", data)
    assert r.status_code == 200
    assert r.json()["duplicate"] is True and r.json()["doc_id"] == first["doc_id"]
    assert len(wf.ingests) == 1


def test_failed_doc_reupload_restarts_workflow(env):
    client, _, repo, wf = env
    data = make_pdf(["retry"])
    doc_id = up(client, "a.pdf", data).json()["doc_id"]
    repo.set_status(doc_id, "FAILED", error_code="FILE_CORRUPTED")
    r = up(client, "a.pdf", data)
    assert r.status_code == 202 and r.json()["status"] == "RECEIVED"
    assert r.json()["error_code"] is None
    assert len(wf.ingests) == 2


def test_unsupported_file_rejected(env):
    client, _, repo, wf = env
    r = up(client, "evil.exe", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\xff\xff")
    assert r.status_code == 415
    assert r.json()["code"] == "UNSUPPORTED_FORMAT"
    assert wf.ingests == [] and repo.list()[1] == 0


def test_extension_cannot_fake_mime(env):
    client, *_ = env
    r = up(client, "fake.pdf", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\xff\xff")
    assert r.status_code == 415


def test_empty_and_too_large(env):
    client, *_ = env
    assert up(client, "a.pdf", b"").status_code == 400
    r = up(client, "a.txt", b"x" * 10_001)
    assert r.status_code == 413 and r.json()["code"] == "FILE_TOO_LARGE"


def test_docx_detected_by_content(docx_bytes):
    assert detect_mime("x.bin", docx_bytes).endswith("wordprocessingml.document")
    assert validate_upload("../../x.docx", docx_bytes, 10**7).file_name == "x.docx"


def test_batch_mixed(env):
    client, _, _, wf = env
    files = [
        ("files", ("a.pdf", make_pdf(["một"]))),
        ("files", ("b.txt", b"hello text")),
        ("files", ("c.exe", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\xff\xff")),
    ]
    r = client.post("/documents/batch", files=files)
    assert r.status_code == 200
    res = r.json()["results"]
    assert [x["ok"] for x in res] == [True, True, False]
    assert res[2]["code"] == "UNSUPPORTED_FORMAT"
    assert len(wf.ingests) == 2


def test_list_filter_and_pagination(env):
    client, _, repo, _ = env
    ids = [up(client, f"d{i}.txt", f"nội dung {i}".encode()).json()["doc_id"] for i in range(5)]
    repo.set_status(ids[0], "INDEXED", chunk_count=3)
    repo.set_status(ids[1], "INDEXED", chunk_count=4)

    body = client.get("/documents", params={"status": "INDEXED"}).json()
    assert body["total"] == 2 and {d["doc_id"] for d in body["items"]} == set(ids[:2])

    page = client.get("/documents", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5 and len(page["items"]) == 2

    assert client.get("/documents", params={"q": "d3"}).json()["total"] == 1
    assert client.get("/documents", params={"status": "BOGUS"}).status_code == 422


def test_detail_includes_live_progress_when_running(env):
    client, _, repo, wf = env
    doc_id = up(client).json()["doc_id"]
    wf.progress = "OCR 3/10"
    d = client.get(f"/documents/{doc_id}").json()
    assert d["status"] == "RECEIVED" and d["progress"] == "OCR 3/10"

    repo.set_status(doc_id, "INDEXED", chunk_count=7)
    d = client.get(f"/documents/{doc_id}").json()
    assert d["progress"] is None and d["chunk_count"] == 7


def test_detail_survives_temporal_down(env):
    client, _, _, wf = env
    doc_id = up(client).json()["doc_id"]

    async def boom(_):
        raise RuntimeError("temporal down")

    wf.get_progress = boom
    r = client.get(f"/documents/{doc_id}")
    assert r.status_code == 200 and r.json()["progress"] is None


def test_detail_404(env):
    client, *_ = env
    assert client.get("/documents/nope").status_code == 404


def test_review_only_when_needs_review(env):
    client, _, repo, wf = env
    doc_id = up(client).json()["doc_id"]
    assert (
        client.post(f"/documents/{doc_id}/review", params={"decision": "approve"}).status_code
        == 409
    )
    repo.set_status(doc_id, "NEEDS_REVIEW")
    assert (
        client.post(f"/documents/{doc_id}/review", params={"decision": "maybe"}).status_code == 422
    )
    r = client.post(f"/documents/{doc_id}/review", params={"decision": "approve"})
    assert r.status_code == 200
    assert wf.reviews == [(doc_id, "approve")]


def test_reindex_bumps_version(env):
    client, _, repo, wf = env
    doc_id = up(client).json()["doc_id"]
    assert client.post(f"/documents/{doc_id}/reindex").status_code == 409
    repo.set_status(doc_id, "INDEXED", chunk_count=5, index_version=1)
    r = client.post(f"/documents/{doc_id}/reindex")
    assert r.status_code == 202 and r.json()["index_version"] == 2
    assert wf.reindexes[0].doc_id == doc_id and wf.reindexes[0].index_version == 2
    assert wf.reindexes[0].file_name == "a.pdf"


def test_cancel(env):
    client, _, repo, wf = env
    doc_id = up(client).json()["doc_id"]
    r = client.post(f"/documents/{doc_id}/cancel")
    assert r.status_code == 202 and wf.cancels == [doc_id]
    repo.set_status(doc_id, "INDEXED")
    assert client.post(f"/documents/{doc_id}/cancel").status_code == 409
    assert client.post("/documents/nope/cancel").status_code == 404


def test_cli_wiring():
    from typer.testing import CliRunner

    from ingest.cli import app

    out = CliRunner().invoke(app, ["--help"]).output
    for cmd in ("upload", "status", "list", "review", "reindex", "cancel", "api", "worker"):
        assert cmd in out


def test_progress_and_cancel_target_reindex_workflow_after_restart(env):
    """Id reindex suy ra từ DB (không nhớ trong RAM), nên API restart vẫn tìm đúng."""
    client, _, repo, wf = env
    doc_id = up(client).json()["doc_id"]
    repo.set_status(doc_id, "INDEXING", index_version=3)  # reindex v3 đang chạy
    client.get(f"/documents/{doc_id}")
    client.post(f"/documents/{doc_id}/cancel")
    assert wf.progress_ids[-1] == f"reindex-{doc_id}-v3" == wf.cancel_ids[-1]
    repo.set_status(doc_id, "INDEXING", index_version=1)  # ingest lần đầu
    client.get(f"/documents/{doc_id}")
    assert wf.progress_ids[-1] == f"ingest-{doc_id}"


async def test_temporal_client_is_stateless_for_reindex():
    from ingest.api.workflow_client import TemporalWorkflowClient, active_workflow_id

    seen = []

    class Handle:
        def __init__(self, wid):
            self.wid = wid

        async def cancel(self):
            seen.append(("cancel", self.wid))

        async def query(self, name, result_type=None):
            seen.append((name, self.wid))
            return "INDEXING"

    class C:
        def get_workflow_handle(self, wid):
            return Handle(wid)

    wid = active_workflow_id("d1", "INDEXING", 2)
    fresh = TemporalWorkflowClient(C())  # client mới, chưa từng start reindex
    await fresh.cancel("d1", wid)
    assert await fresh.get_progress("d1", wid) == "INDEXING"
    assert seen == [("cancel", "reindex-d1-v2"), ("get_progress", "reindex-d1-v2")]


def test_start_failure_rolls_back_restart_and_maps_409(env):
    from temporalio.exceptions import WorkflowAlreadyStartedError

    client, _, repo, wf = env
    doc_id = up(client).json()["doc_id"]
    repo.set_status(doc_id, "FAILED", error_code="FILE_CORRUPTED")

    async def boom(inp):
        raise WorkflowAlreadyStartedError("ingest-x", "DocumentIngestionWorkflow")

    wf.start_ingest = boom
    r = up(client)
    assert r.status_code == 409
    rec = repo.get(doc_id)  # không kẹt RECEIVED
    assert (rec.status, rec.error_code) == ("FAILED", "FILE_CORRUPTED")


def test_start_failure_on_new_doc_leaves_restartable_row(env):
    client, _, repo, wf = env

    async def boom(inp):
        raise RuntimeError("temporal down")

    wf.start_ingest = boom
    data = make_pdf(["tài liệu mới"])
    with pytest.raises(RuntimeError):
        up(client, data=data)
    rec = repo.get(compute_doc_id(data))
    assert (rec.status, rec.error_code) == ("FAILED", "START_FAILED")


def test_ui_page_served(env):
    client, *_ = env
    r = client.get("/")
    assert r.status_code == 200 and "Nạp tài liệu" in r.text
    assert "/documents/" in r.text


def test_markdown_endpoint(env):
    client, storage, *_ = env
    doc_id = up(client).json()["doc_id"]
    assert client.get(f"/documents/{doc_id}/markdown").status_code == 404
    storage.put(keys.md_key(doc_id), "# Tiêu đề\n\n| a |\n|---|".encode())
    r = client.get(f"/documents/{doc_id}/markdown")
    assert r.status_code == 200 and r.text.startswith("# Tiêu đề")
    assert r.headers["content-type"].startswith("text/markdown")
    assert client.get("/documents/khong-co/markdown").status_code == 404


def test_legacy_mode_gets_own_doc_id_and_flag(env):
    client, _, _, wf = env
    data = make_pdf(["so sánh hai chế độ"])
    new = up(client, data=data).json()
    old = client.post(
        "/documents", files={"file": ("a.pdf", data)}, data={"extract_media": "false"}
    ).json()
    assert new["doc_id"] == compute_doc_id(data) and new["extract_media"] is True
    assert old["doc_id"].startswith("legacy-") and len(old["doc_id"]) == 64
    assert old["extract_media"] is False and not old["duplicate"]
    assert [i.extract_media for i in wf.ingests] == [True, False]
    items = {d["doc_id"]: d["extract_media"] for d in client.get("/documents").json()["items"]}
    assert items == {new["doc_id"]: True, old["doc_id"]: False}


def test_list_multiple_statuses(env):
    client, _, repo, _ = env
    ids = [up(client, f"{i}.pdf", make_pdf([f"s{i}"])).json()["doc_id"] for i in range(3)]
    repo.set_status(ids[0], "INDEXED")
    repo.set_status(ids[1], "FAILED", error_code="X")
    r = client.get("/documents?status=INDEXED,FAILED").json()
    assert r["total"] == 2 and {d["doc_id"] for d in r["items"]} == set(ids[:2])
    assert client.get("/documents?status=RECEIVED").json()["total"] == 1
    assert client.get("/documents?status=INDEXED,NOPE").status_code == 422


def test_stats_has_all_statuses(env):
    from ingest.core.db import STATUSES

    client, _, repo, _ = env
    assert client.get("/stats").json() == {
        "total": 0,
        "chunks": 0,
        "by_status": dict.fromkeys(STATUSES, 0),
    }
    a = up(client, "a.pdf", make_pdf(["a"])).json()["doc_id"]
    b = up(client, "b.pdf", make_pdf(["b"])).json()["doc_id"]
    up(client, "c.pdf", make_pdf(["c"]))
    repo.set_status(a, "INDEXED", chunk_count=10)
    repo.set_status(b, "INDEXED", chunk_count=5)
    body = client.get("/stats").json()
    assert body["total"] == 3 and body["chunks"] == 15
    assert body["by_status"]["INDEXED"] == 2 and body["by_status"]["RECEIVED"] == 1
    assert body["by_status"]["CANCELLED"] == 0 and len(body["by_status"]) == len(STATUSES)


def test_raw_download(env):
    client, *_ = env
    data = make_pdf(["gốc"])
    doc_id = up(client, "báo cáo.pdf", data).json()["doc_id"]
    r = client.get(f"/documents/{doc_id}/raw")
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''b%C3%A1o%20c%C3%A1o.pdf"
    )
    assert client.get("/documents/khong-co/raw").status_code == 404


def test_raw_missing_file_is_404(env):
    client, _, repo, _ = env
    repo.get_or_create("d1", "x.pdf", "application/pdf", 1)
    assert client.get("/documents/d1/raw").status_code == 404


def _put_chunks(storage, doc_id, version, n_batches, per=2):
    import json

    i = 0
    for b in range(n_batches):
        rows = []
        for _ in range(per):
            rows.append(
                {
                    "chunk_index": i,
                    "text": f"đoạn {i}",
                    "heading_path": "H",
                    "page_start": 1,
                    "page_end": 1,
                    "content_hash": f"h{i}",
                }
            )
            i += 1
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        storage.put(keys.chunk_batch_key(doc_id, version, b), body.encode())


def test_chunks_numeric_batch_order_and_paging(env):
    client, storage, repo, _ = env
    repo.get_or_create("d1", "x.pdf")
    repo.set_status("d1", "INDEXED", index_version=1)
    _put_chunks(storage, "d1", 1, 12)  # batch-10, batch-11 phải đứng sau batch-9
    r = client.get("/documents/d1/chunks?limit=200").json()
    assert r["total"] == 24 and r["index_version"] == 1
    assert [c["chunk_index"] for c in r["items"]] == list(range(24))
    assert r["items"][3]["text"] == "đoạn 3"
    p = client.get("/documents/d1/chunks?offset=20&limit=3").json()
    assert [c["chunk_index"] for c in p["items"]] == [20, 21, 22]
    assert (p["offset"], p["limit"], p["total"]) == (20, 3, 24)
    assert client.get("/documents/d1/chunks?limit=201").status_code == 422


def test_chunks_version_and_404(env):
    client, storage, repo, _ = env
    repo.get_or_create("d1", "x.pdf")
    assert client.get("/documents/d1/chunks").status_code == 404
    _put_chunks(storage, "d1", 1, 1)
    _put_chunks(storage, "d1", 2, 2)
    repo.set_status("d1", "INDEXED", index_version=2)
    assert client.get("/documents/d1/chunks").json()["total"] == 4  # mặc định = index_version
    assert client.get("/documents/d1/chunks?version=1").json()["total"] == 2
    assert client.get("/documents/d1/chunks?version=3").status_code == 404
    assert client.get("/documents/khong-co/chunks").status_code == 404


def test_cancel_running_isolates_failures(env):
    client, _, repo, wf = env
    ids = [up(client, f"{i}.pdf", make_pdf([f"r{i}"])).json()["doc_id"] for i in range(4)]
    repo.set_status(ids[0], "INDEXING")
    repo.set_status(ids[1], "INDEXED")  # không chạy, bỏ qua
    orig = wf.cancel

    async def flaky(doc_id, workflow_id=None):
        if doc_id == ids[2]:
            raise RuntimeError("temporal down")
        await orig(doc_id, workflow_id)

    wf.cancel = flaky
    r = client.post("/documents/cancel-running")
    assert r.status_code == 202
    body = r.json()
    assert set(body["requested"]) == {ids[0], ids[3]}
    assert body["failed"] == [{"doc_id": ids[2], "detail": "temporal down"}]
