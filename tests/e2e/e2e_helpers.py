"""Helper dùng chung cho E2E (không đặt trong conftest để khỏi đụng tests/conftest.py)."""

import asyncio
import io
import os
import time

import httpx
import pymupdf

from ingest.core.config import get_settings

API_URL = os.environ.get("INGEST_E2E_API_URL", "http://localhost:18000").rstrip("/")


class Stack:
    def __init__(self) -> None:
        from qdrant_client import QdrantClient
        from temporalio.client import Client

        from ingest.core.storage import S3Storage
        from ingest.index.vectorstore import VectorStore  # noqa: F401

        self.s = get_settings()
        self.http = httpx.Client(base_url=API_URL, timeout=60)
        self.qdrant = QdrantClient(url=self.s.qdrant_url)
        self.storage = S3Storage(
            self.s.s3_endpoint, self.s.s3_access_key, self.s.s3_secret_key,
            self.s.s3_bucket, self.s.s3_region,
        )  # fmt: skip
        self._temporal_cls = Client

    # --- API ---
    def upload(self, name: str, data: bytes, base: httpx.Client | None = None) -> httpx.Response:
        return (base or self.http).post("/documents", files={"file": (name, data)})

    def doc(self, doc_id: str, base: httpx.Client | None = None) -> dict:
        r = (base or self.http).get(f"/documents/{doc_id}")
        r.raise_for_status()
        return r.json()

    def wait(self, doc_id, targets, timeout=180, base=None, pred=None) -> dict:
        targets = {targets} if isinstance(targets, str) else set(targets)
        end = time.time() + timeout
        d: dict = {}
        while time.time() < end:
            d = self.doc(doc_id, base)
            if d["status"] in targets and (pred is None or pred(d)):
                return d
            time.sleep(1)
        raise AssertionError(f"{doc_id} không tới {targets} sau {timeout}s, cuối cùng: {d}")

    # --- Qdrant ---
    def points(self, doc_id: str, version: int | None = None) -> list:
        from qdrant_client import models as qm

        must = [qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]
        if version is not None:
            must.append(qm.FieldCondition(key="index_version", match=qm.MatchValue(value=version)))
        out, off = [], None
        while True:
            pts, off = self.qdrant.scroll(
                self.s.qdrant_collection, scroll_filter=qm.Filter(must=must), limit=256,
                offset=off, with_payload=True, with_vectors=False,
            )  # fmt: skip
            out += pts
            if off is None:
                return out

    # --- Temporal ---
    def run(self, coro_fn):
        """coro_fn(client) -> kết quả, chạy trong event loop riêng."""

        async def go():
            c = await self._temporal_cls.connect(
                self.s.temporal_address, namespace=self.s.temporal_namespace
            )
            return await coro_fn(c)

        return asyncio.run(go())

    def wf_describe(self, workflow_id: str):
        async def f(c):
            return await c.get_workflow_handle(workflow_id).describe()

        return self.run(f)


# ---------- tạo file mẫu (mỗi lần chạy có nội dung duy nhất) ----------


def text_pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 80
    for ln in lines:
        page.insert_text((60, y), ln, fontsize=12)
        y += 20
    return doc.tobytes()


def scanned_pdf(pages: list[list[str]]) -> bytes:
    """PDF chỉ có ảnh, không lớp text (render chữ rồi nhúng bitmap)."""
    out = pymupdf.open()
    for lines in pages:
        src = pymupdf.open()
        p = src.new_page()
        y = 100
        for ln in lines:
            p.insert_text((60, y), ln, fontsize=28)
            y += 50
        png = p.get_pixmap(dpi=110).tobytes("jpg", jpg_quality=70)
        np_ = out.new_page()
        np_.insert_image(np_.rect, stream=png)
    return out.tobytes()


def docx_bytes(tag: str) -> bytes:
    import docx

    d = docx.Document()
    d.add_heading(f"Hợp đồng {tag}", level=1)
    d.add_paragraph(f"Điều 3: Thanh toán trong vòng 30 ngày kể từ ngày nhận hóa đơn {tag}.")
    d.add_heading("Bảo hành", level=2)
    d.add_paragraph("Thời hạn bảo hành thiết bị là 24 tháng.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def xlsx_bytes(tag: str) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Sản phẩm", "Số lượng", "Mã"])
    ws.append(["Bàn phím", 12, tag])
    ws.append(["Chuột", 30, tag + "x"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def html_bytes(tag: str) -> bytes:
    return (
        f"<html><head><title>Trang {tag}</title></head><body><h1>Chính sách {tag}</h1>"
        "<p>Khách hàng được đổi trả trong vòng 7 ngày.</p><h2>Vận chuyển</h2>"
        "<p>Miễn phí vận chuyển cho đơn trên 500.000 đồng.</p></body></html>"
    ).encode()


def pptx_bytes(tag: str) -> bytes:
    from pptx import Presentation

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = f"Kế hoạch {tag}"
    s.placeholders[1].text = "Mục tiêu quý bốn là mở rộng thị trường."
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
