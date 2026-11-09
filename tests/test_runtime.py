"""core.runtime: dựng storage, repo, kết nối Temporal, chạy Worker (giả lập client ngoài)."""

from ingest.core import runtime
from ingest.core.config import Settings


def S(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_make_storage_ensures_bucket(monkeypatch):
    created = []

    class FakeS3:
        def __init__(self, *args):
            self.args = args

        def ensure_bucket(self):
            created.append(self.args)

    monkeypatch.setattr(runtime, "S3Storage", FakeS3)
    st = runtime.make_storage(S(s3_bucket="b1", s3_region="r1"))
    assert st.args == ("http://localhost:9000", "minioadmin", "minioadmin", "b1", "r1")
    assert created == [st.args]


def test_make_repo(monkeypatch):
    monkeypatch.setattr(runtime, "session_factory", lambda url: ("repo", url))
    assert runtime.make_repo(S(database_url="sqlite://")) == ("repo", "sqlite://")


async def test_connect(monkeypatch):
    seen = {}

    async def fake_connect(addr, namespace):
        seen.update(addr=addr, ns=namespace)
        return "client"

    monkeypatch.setattr(runtime.Client, "connect", fake_connect)
    assert await runtime.connect(S(temporal_address="t:7233", temporal_namespace="ns")) == "client"
    assert seen == {"addr": "t:7233", "ns": "ns"}


def test_run_main_builds_and_runs_worker(monkeypatch):
    settings = S()
    ran = []

    class FakeWorker:
        async def run(self):
            ran.append("run")

    async def fake_connect(s):
        assert s is settings
        return "client"

    async def build(s, client):
        assert (s, client) == (settings, "client")
        return FakeWorker()

    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "connect", fake_connect)
    runtime.run_main(build)
    assert ran == ["run"]
