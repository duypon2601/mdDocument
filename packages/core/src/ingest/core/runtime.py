"""Phần dùng chung để dựng worker: kết nối Temporal, storage, Metadata DB, vòng chạy Worker."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from ingest.core.config import Settings, get_settings
from ingest.core.db import DocumentRepository, session_factory
from ingest.core.storage import S3Storage


def make_storage(s: Settings) -> S3Storage:
    st = S3Storage(s.s3_endpoint, s.s3_access_key, s.s3_secret_key, s.s3_bucket, s.s3_region)
    st.ensure_bucket()
    return st


def make_repo(s: Settings) -> DocumentRepository:
    return session_factory(s.database_url)


async def connect(s: Settings) -> Client:
    return await Client.connect(s.temporal_address, namespace=s.temporal_namespace)


async def run_worker(worker: Worker | list[Worker]) -> None:
    """Chạy một hoặc nhiều Worker trong cùng tiến trình."""
    logging.basicConfig(level=logging.INFO)
    workers = worker if isinstance(worker, list) else [worker]
    await asyncio.gather(*(w.run() for w in workers))


def run_main(build) -> None:
    """build(settings, client) -> Worker hoặc list[Worker] (coroutine)."""

    async def _run() -> None:
        s = get_settings()
        client = await connect(s)
        await run_worker(await build(s, client))

    asyncio.run(_run())
