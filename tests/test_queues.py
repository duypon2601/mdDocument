"""GET /temporal/queues: ảnh chụp task queue lấy từ Temporal, kèm tên file từ Metadata DB."""

from fastapi.testclient import TestClient

from ingest.api.app import create_app
from ingest.api.queues import ACTIVITY_QUEUE, _doc_id_of
from ingest.core.config import Settings
from ingest.core.db import session_factory
from ingest.core.storage import MemoryStorage


def queue(name: str, expects_workflow: bool = False) -> dict:
    part = {
        "pollers": [],
        "backlog": 0,
        "backlog_age_s": 0.0,
        "add_rate": 0.0,
        "dispatch_rate": 0.0,
    }
    return {"name": name, "expects_workflow": expects_workflow, "workflow": part, "activity": part}


class FakeInspector:
    def __init__(self, running: list[dict] | None = None, fail: Exception | None = None) -> None:
        self.running = running or []
        self.fail = fail

    async def snapshot(self) -> dict:
        if self.fail:
            raise self.fail
        return {
            "fetched_at": "2026-11-10T00:00:00+00:00",
            "queues": [queue("ingest-tq", True), queue("convert-tq"), queue("index-tq")],
            "running": [dict(r) for r in self.running],
            "running_truncated": False,
        }


def make_client(inspector, repo=None) -> TestClient:
    repo = repo or session_factory("sqlite:///:memory:")
    return TestClient(
        create_app(MemoryStorage(), repo, None, Settings(), queue_inspector=inspector)
    )


def running(wid: str, doc_id: str | None) -> dict:
    return {
        "workflow_id": wid,
        "workflow_type": "DocumentIngestionWorkflow",
        "doc_id": doc_id,
        "started_at": None,
        "activities": [],
    }


def test_queues_returns_snapshot():
    body = make_client(FakeInspector()).get("/temporal/queues").json()
    assert [q["name"] for q in body["queues"]] == ["ingest-tq", "convert-tq", "index-tq"]
    assert body["running"] == []


def test_queues_adds_file_name_and_status_from_db():
    repo = session_factory("sqlite:///:memory:")
    repo.get_or_create("d1", "bao-cao.pdf", "application/pdf", 10)
    repo.set_status("d1", "CONVERTING")
    insp = FakeInspector([running("ingest-d1", "d1"), running("other", None)])
    rows = make_client(insp, repo).get("/temporal/queues").json()["running"]
    assert (rows[0]["file_name"], rows[0]["status"]) == ("bao-cao.pdf", "CONVERTING")
    assert (rows[1]["file_name"], rows[1]["status"]) == (None, None)


def test_queues_503_without_temporal():
    r = make_client(None).get("/temporal/queues")
    assert r.status_code == 503 and r.json()["code"] == "TEMPORAL_UNAVAILABLE"


def test_queues_503_when_temporal_errors():
    r = make_client(FakeInspector(fail=RuntimeError("không kết nối được"))).get("/temporal/queues")
    assert r.status_code == 503
    assert r.json() == {"code": "TEMPORAL_UNAVAILABLE", "detail": "không kết nối được"}


def test_doc_id_of_workflow_ids():
    assert _doc_id_of("ingest-abc") == "abc"
    assert _doc_id_of("reindex-abc-v3") == "abc"
    assert _doc_id_of("hoc-bao-cao.pdf") is None


def test_activity_queue_matches_ingestion_workflow():
    """Bảng activity→queue phải khớp workflow thật ở package index."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / (
        "packages/index/src/ingest/index/workflows/ingestion.py"
    )
    tree = ast.parse(src.read_text(encoding="utf-8"))
    queue_of = {"INGEST_TQ": "ingest-tq", "CONVERT_TQ": "convert-tq", "INDEX_TQ": "index-tq"}
    found = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "execute_activity"
        ):
            continue
        name = node.args[0].value
        tq = next(k.value.id for k in node.keywords if k.arg == "task_queue")
        found[name] = queue_of[tq]
    assert found == ACTIVITY_QUEUE
