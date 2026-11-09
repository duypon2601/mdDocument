"""Duyệt OCR: review_enabled là cấu hình server (không theo request), nên test dựng
một API phụ trên cổng riêng với INGEST_REVIEW_ENABLED=true và ngưỡng tin cậy > 1."""

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from e2e.e2e_helpers import scanned_pdf

PORT = 18001


@pytest.fixture
def review_api(tmp_path):
    env = {**os.environ, "INGEST_REVIEW_ENABLED": "true", "INGEST_MIN_OCR_CONFIDENCE": "1.5"}
    log = open(tmp_path / "api-review.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ingest.api.app:create_default_app", "--factory",
         "--port", str(PORT)],
        env=env, stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    client = httpx.Client(base_url=f"http://localhost:{PORT}", timeout=60)
    try:
        for _ in range(60):
            try:
                with socket.create_connection(("localhost", PORT), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("API phụ không khởi động được")
        yield client
    finally:
        client.close()
        proc.terminate()
        proc.wait(10)


@pytest.mark.parametrize("decision,final", [("approve", "INDEXED"), ("reject", "FAILED")])
def test_review_flow(stack, review_api, tag, decision, final):
    data = scanned_pdf([["REVIEW REQUIRED", f"CODE {str(int(tag, 16))[:8]}"]])
    r = stack.upload(f"{tag}-review.pdf", data, base=review_api)
    assert r.status_code == 202, r.text
    doc_id = r.json()["doc_id"]
    stack.wait(doc_id, "NEEDS_REVIEW", base=review_api, timeout=90)
    assert stack.doc(doc_id, review_api)["progress"] == "NEEDS_REVIEW"
    rr = review_api.post(f"/documents/{doc_id}/review", params={"decision": decision})
    assert rr.status_code == 200
    d = stack.wait(doc_id, final, base=review_api, timeout=120)
    if decision == "reject":
        assert d["error_code"] == "OCR_REJECTED"
        assert stack.wf_describe(f"ingest-{doc_id}").status.name == "FAILED"
    else:
        assert len(stack.points(doc_id)) == d["chunk_count"] >= 1
    # không còn ở NEEDS_REVIEW thì duyệt lại bị từ chối
    assert (
        review_api.post(f"/documents/{doc_id}/review", params={"decision": "approve"}).status_code
        == 409
    )
