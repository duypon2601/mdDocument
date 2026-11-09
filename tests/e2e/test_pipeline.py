"""Kịch bản E2E chính: định dạng, OCR, dedup, lỗi, reindex, huỷ, tìm kiếm."""

import json

import httpx
import pytest

from e2e.e2e_helpers import (
    docx_bytes,
    html_bytes,
    pptx_bytes,
    scanned_pdf,
    text_pdf,
    xlsx_bytes,
)
from ingest.core import keys

PAYLOAD_FIELDS = {
    "doc_id", "index_version", "file_name", "heading_path", "page_start", "page_end",
    "chunk_index", "text", "content_hash", "embedding_model", "created_at",
}  # fmt: skip


def _upload_ok(stack, name, data) -> str:
    r = stack.upload(name, data)
    assert r.status_code == 202, r.text
    assert r.json()["duplicate"] is False
    return r.json()["doc_id"]


def _chunk_lines(stack, doc_id, version) -> int:
    n = 0
    for k in stack.storage.list_keys(f"chunks/{doc_id}/v{version}/"):
        n += len([ln for ln in stack.storage.get(k).decode().splitlines() if ln.strip()])
    return n


def _assert_indexed(stack, doc_id, file_name, version=1) -> dict:
    d = stack.wait(doc_id, "INDEXED")
    assert d["index_version"] == version
    assert d["chunk_count"] >= 1
    assert d["embedding_model"] == stack.s.embed_model
    pts = stack.points(doc_id, version)
    assert len(pts) == d["chunk_count"] == _chunk_lines(stack, doc_id, version)
    idx = set()
    for p in pts:
        pl = p.payload
        assert PAYLOAD_FIELDS <= set(pl), f"thiếu field: {PAYLOAD_FIELDS - set(pl)}"
        assert pl["doc_id"] == doc_id and pl["index_version"] == version
        assert pl["file_name"] == file_name
        assert pl["embedding_model"] == stack.s.embed_model
        assert pl["content_hash"].startswith("sha256:")
        assert pl["text"].strip()
        assert p.id == keys.point_id(doc_id, version, pl["chunk_index"])
        idx.add(pl["chunk_index"])
    assert idx == set(range(len(pts)))
    assert stack.storage.exists(keys.md_key(doc_id))
    wf = stack.wf_describe(f"ingest-{doc_id}")
    assert wf.status.name == "COMPLETED"
    return d


@pytest.mark.parametrize(
    "name,maker",
    [
        (
            "tai-lieu.pdf",
            lambda t: text_pdf([f"Báo cáo doanh thu {t}", "Doanh thu quý ba tăng 12%."]),
        ),
        ("hop-dong.docx", docx_bytes),
        ("chinh-sach.html", html_bytes),
        ("kho.xlsx", xlsx_bytes),
        ("ke-hoach.pptx", pptx_bytes),
        ("ghi-chu.md", lambda t: f"# Ghi chú {t}\n\nNội dung ghi chú về dự án.\n".encode()),
        ("ghi-chu.txt", lambda t: f"Văn bản thuần {t}. Dòng thứ hai về kế hoạch.\n".encode()),
    ],
)
def test_format_reaches_indexed(stack, tag, name, maker):
    data = maker(tag)
    data = data.encode() if isinstance(data, str) else data
    doc_id = _upload_ok(stack, f"{tag}-{name}", data)
    _assert_indexed(stack, doc_id, f"{tag}-{name}")
    assert stack.storage.get(keys.md_key(doc_id)).decode().strip()


def test_text_pdf_markdown_contains_text(stack, tag):
    doc_id = _upload_ok(stack, f"{tag}.pdf", text_pdf([f"Mã tham chiếu {tag}"]))
    stack.wait(doc_id, "INDEXED")
    assert tag in stack.storage.get(keys.md_key(doc_id)).decode()


def test_scanned_pdf_ocr_text_in_markdown(stack, tag):
    digits = str(int(tag, 16))[:8]
    data = scanned_pdf([["QUARTERLY REPORT", f"INVOICE {digits}"]])
    doc_id = _upload_ok(stack, f"{tag}-scan.pdf", data)
    _assert_indexed(stack, doc_id, f"{tag}-scan.pdf")
    md = stack.storage.get(keys.md_key(doc_id)).decode().upper()
    assert "QUARTERLY" in md and "REPORT" in md
    assert stack.storage.list_keys(f"md-raw/{doc_id}/ocr/"), "phải có kết quả OCR trung gian"


def test_duplicate_upload_starts_no_new_workflow(stack, tag):
    data = text_pdf([f"Trùng lặp {tag}"])
    doc_id = _upload_ok(stack, f"{tag}.pdf", data)
    stack.wait(doc_id, "INDEXED")
    run1 = stack.wf_describe(f"ingest-{doc_id}").run_id
    r = stack.upload(f"{tag}.pdf", data)
    assert r.status_code == 200 and r.json()["duplicate"] is True
    assert r.json()["doc_id"] == doc_id
    assert stack.wf_describe(f"ingest-{doc_id}").run_id == run1
    assert stack.doc(doc_id)["status"] == "INDEXED"
    assert len(stack.points(doc_id)) == stack.doc(doc_id)["chunk_count"]


def test_corrupted_pdf_fails_with_file_corrupted(stack, tag):
    data = b"%PDF-1.4\n" + f"khong phai pdf that {tag}".encode() * 20
    doc_id = _upload_ok(stack, f"{tag}-hong.pdf", data)
    d = stack.wait(doc_id, "FAILED")
    assert d["error_code"] == "FILE_CORRUPTED"
    wf = stack.wf_describe(f"ingest-{doc_id}")
    assert wf.status.name == "FAILED"
    assert stack.points(doc_id) == []


def test_unsupported_binary_rejected_by_api(stack, tag):
    r = stack.upload(f"{tag}.bin", bytes(range(256)) * 8 + tag.encode())
    assert r.status_code == 415
    assert r.json()["code"] == "UNSUPPORTED_FORMAT"


def test_empty_file_rejected(stack):
    r = stack.upload("rong.pdf", b"")
    assert r.status_code == 400 and r.json()["code"] == "EMPTY_FILE"


def test_reupload_after_failed_starts_new_run(stack, tag):
    data = b"%PDF-1.4\n" + f"hong lan hai {tag}".encode() * 20
    doc_id = _upload_ok(stack, f"{tag}-hong.pdf", data)
    stack.wait(doc_id, "FAILED")
    run1 = stack.wf_describe(f"ingest-{doc_id}").run_id
    r = stack.upload(f"{tag}-hong.pdf", data)
    assert r.status_code == 202, r.text
    assert r.json()["duplicate"] is False
    stack.wait(doc_id, "FAILED")
    run2 = stack.wf_describe(f"ingest-{doc_id}").run_id
    assert run2 != run1, "upload lại sau FAILED phải sinh run mới"


def test_reindex_bumps_version_and_replaces_points(stack, tag):
    paras = "\n\n".join(
        f"## Mục {i} {tag}\n\n" + ("Nội dung chi tiết của mục này nói về quy trình. " * 40)
        for i in range(8)
    )
    doc_id = _upload_ok(stack, f"{tag}.md", f"# Quy trình {tag}\n\n{paras}\n".encode())
    d1 = stack.wait(doc_id, "INDEXED")
    n1 = d1["chunk_count"]
    assert n1 >= 2
    r = stack.http.post(f"/documents/{doc_id}/reindex")
    assert r.status_code == 202 and r.json()["index_version"] == 2
    d2 = stack.wait(doc_id, "INDEXED", pred=lambda d: d["index_version"] == 2)
    assert d2["chunk_count"] == n1
    assert stack.points(doc_id, 1) == [], "point version cũ phải bị xoá"
    assert len(stack.points(doc_id, 2)) == n1
    assert len(stack.points(doc_id)) == n1
    # reindex ở trạng thái không phải INDEXED thì bị từ chối
    bad = stack.upload(f"{tag}-x.pdf", b"%PDF-1.4\n" + tag.encode() * 30)
    stack.wait(bad.json()["doc_id"], "FAILED")
    assert stack.http.post(f"/documents/{bad.json()['doc_id']}/reindex").status_code == 409


def test_cancel_during_processing(stack, tag):
    pages = [[f"PAGE {i} CANCEL TEST", f"CODE {tag[:6]}"] for i in range(24)]
    doc_id = _upload_ok(stack, f"{tag}-cancel.pdf", scanned_pdf(pages))
    stack.wait(doc_id, "CONVERTING", timeout=30)
    r = stack.http.post(f"/documents/{doc_id}/cancel")
    assert r.status_code == 202
    stack.wait(doc_id, "CANCELLED", timeout=120)
    assert stack.wf_describe(f"ingest-{doc_id}").status.name in {"CANCELED", "CANCELLED"}
    assert stack.points(doc_id) == []
    assert stack.http.post(f"/documents/{doc_id}/cancel").status_code == 409


def test_vietnamese_search_returns_right_document(stack, tag):
    a = (
        f"# Thanh toán {tag}\n\nBên mua phải thanh toán toàn bộ tiền hàng bằng chuyển khoản "
        "ngân hàng trong vòng ba mươi ngày kể từ khi nhận hóa đơn.\n"
    )
    b = (
        f"# Nấu ăn {tag}\n\nCông thức nấu phở bò gồm xương ống, hành nướng, quế, hồi và thịt bò "
        "tái, ninh nhiều giờ cho nước dùng trong và ngọt.\n"
    )
    id_a = _upload_ok(stack, f"{tag}-a.md", a.encode())
    id_b = _upload_ok(stack, f"{tag}-b.md", b.encode())
    stack.wait(id_a, "INDEXED")
    stack.wait(id_b, "INDEXED")

    def top(query: str) -> str:
        r = httpx.post(
            f"{stack.s.embed_base_url}/embeddings",
            json={"model": stack.s.embed_model, "input": [query]},
            headers={"Authorization": f"Bearer {stack.s.embed_api_key}"},
            timeout=60,
        )
        r.raise_for_status()
        vec = r.json()["data"][0]["embedding"]
        from qdrant_client import models as qm

        flt = qm.Filter(must=[qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=[id_a, id_b]))])
        res = stack.qdrant.query_points(
            stack.s.qdrant_collection, query=vec, query_filter=flt, limit=1, with_payload=True
        )
        return res.points[0].payload["doc_id"]

    assert top("làm sao để trả tiền hàng cho người bán?") == id_a
    assert top("cách nấu nước dùng phở") == id_b


def test_list_and_status_api(stack, tag):
    doc_id = _upload_ok(stack, f"{tag}-list.md", f"# Danh sách {tag}\n\nnội dung\n".encode())
    stack.wait(doc_id, "INDEXED")
    r = stack.http.get("/documents", params={"status": "INDEXED", "q": tag})
    assert r.status_code == 200
    assert doc_id in [i["doc_id"] for i in r.json()["items"]]
    assert stack.http.get("/documents/khong-ton-tai").status_code == 404
    assert json.dumps(stack.doc(doc_id))
