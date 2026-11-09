import json
from dataclasses import asdict

import pytest
from temporalio.testing import ActivityEnvironment

from ingest.core.db import DocumentRepository, make_engine
from ingest.core.models import StatusUpdate
from ingest.core.storage import MemoryStorage
from ingest.index.status import StatusActivities


def make_repo() -> DocumentRepository:
    repo = DocumentRepository(make_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def test_memory_storage():
    s = MemoryStorage()
    s.put("a/1", b"x")
    s.put("a/2", b"y")
    s.put("b/1", b"z")
    assert s.get("a/1") == b"x"
    assert s.list_keys("a/") == ["a/1", "a/2"]
    assert s.exists("b/1") and not s.exists("b/2")
    s.delete("a/1")
    with pytest.raises(FileNotFoundError):
        s.get("a/1")


def test_repo_get_or_create_idempotent_and_list():
    repo = make_repo()
    r1, c1 = repo.get_or_create("d1", "a.pdf", "application/pdf", 10)
    r2, c2 = repo.get_or_create("d1", "a.pdf")
    assert c1 and not c2 and r1.doc_id == r2.doc_id
    repo.get_or_create("d2", "b.docx")
    items, total = repo.list(limit=1)
    assert total == 2 and len(items) == 1
    repo.set_status("d2", "FAILED", error_code="FILE_CORRUPTED")
    items, total = repo.list(status="FAILED")
    assert [i.doc_id for i in items] == ["d2"] and total == 1
    assert repo.list(q="a.p")[1] == 1


def test_set_status_absolute_and_unknown():
    repo = make_repo()
    repo.get_or_create("d1", "a.pdf")
    repo.set_status("d1", "FAILED", error_code="X")
    repo.set_status("d1", "INDEXED", chunk_count=5, index_version=2, embedding_model="m")
    repo.set_status("d1", "INDEXED", chunk_count=5, index_version=2, embedding_model="m")
    d = repo.get("d1")
    assert (d.status, d.error_code, d.chunk_count, d.index_version) == ("INDEXED", None, 5, 2)
    with pytest.raises(ValueError):
        repo.set_status("d1", "BOGUS")
    with pytest.raises(LookupError):
        repo.set_status("nope", "INDEXED")


async def test_update_status_activity_rerun_and_roundtrip():
    repo = make_repo()
    repo.get_or_create("d1", "a.pdf")
    acts = StatusActivities(repo)
    upd = StatusUpdate(doc_id="d1", status="INDEXED", chunk_count=3)
    assert StatusUpdate(**json.loads(json.dumps(asdict(upd)))) == upd
    env = ActivityEnvironment()
    await env.run(acts.update_status, upd)
    await env.run(acts.update_status, upd)
    assert repo.get("d1").status == "INDEXED" and repo.get("d1").chunk_count == 3


def test_create_schema_postgres_holds_advisory_lock_around_create_all(monkeypatch):
    """Không cần server: ghi lại thứ tự lệnh trên một connection giả."""
    from sqlalchemy import create_engine

    from ingest.core import db

    log: list[str] = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params=None):
            log.append(str(stmt))

        def commit(self):
            log.append("commit")

        def rollback(self):
            log.append("rollback")

    monkeypatch.setattr(db.Base.metadata, "create_all", lambda conn: log.append("create_all"))
    eng = create_engine("postgresql+psycopg://u:p@localhost:1/db")
    monkeypatch.setattr(eng, "connect", lambda: FakeConn())
    DocumentRepository(eng).create_schema()
    assert "pg_advisory_lock" in log[0]
    assert log.index("create_all") == 1
    assert any("pg_advisory_unlock" in s for s in log[2:])


def test_create_schema_sqlite_idempotent():
    repo = make_repo()
    repo.create_schema()
    repo.create_schema()
