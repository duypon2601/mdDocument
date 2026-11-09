"""Worker convert chết giữa chừng OCR, khởi động lại thì tài liệu vẫn tới INDEXED."""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from e2e.e2e_helpers import scanned_pdf

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = Path(os.environ.get("INGEST_E2E_LOG_DIR", "/tmp"))


def _pids(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout
    return [int(p) for p in out.split() if int(p) != os.getpid()]


def _descendants(pid: int) -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout
    kids = [int(p) for p in out.split()]
    return kids + [g for k in kids for g in _descendants(k)]


def test_convert_worker_crash_mid_ocr_recovers(stack, tag):
    roots = _pids("ingest worker convert")
    if not roots:
        pytest.skip("không tìm thấy tiến trình `ingest worker convert` để kill")
    pages = [[f"CRASH TEST PAGE {i}", f"SERIAL {tag[:6]}"] for i in range(30)]
    r = stack.upload(f"{tag}-crash.pdf", scanned_pdf(pages))
    assert r.status_code == 202
    doc_id = r.json()["doc_id"]
    stack.wait(doc_id, "CONVERTING", timeout=30)
    time.sleep(8)  # để OCR chạy dở
    victims = roots + [d for p in roots for d in _descendants(p)]
    for pid in victims:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(2)
    assert stack.doc(doc_id)["status"] == "CONVERTING", "đang OCR dở thì chưa được xong"
    log = open(LOG_DIR / "w-convert.log", "ab")
    subprocess.Popen(
        ["uv", "run", "ingest", "worker", "convert"],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )  # fmt: skip
    d = stack.wait(doc_id, "INDEXED", timeout=420)
    assert len(stack.points(doc_id)) == d["chunk_count"] >= 1
    md = stack.storage.get(f"md/{doc_id}.md").decode().upper()
    assert "CRASH" in md and "PAGE" in md
