"""Pipeline v2: phát hiện sai dấu, gọi lại VLM khi 429, thu nhỏ ảnh, log từng lần gọi.
v1 giữ nguyên hành vi trước chỉnh sửa để so sánh output trên giao diện."""

import logging
import random

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from temporalio.testing import ActivityEnvironment

from ingest.api.app import create_app
from ingest.api.dedup import compute_doc_id, profile_of
from ingest.convert.activities import ConvertActivities, vision_reason
from ingest.convert.ocr import FakeOcr
from ingest.convert.parsers.vn_syllable import bad_diacritic_ratio, is_valid
from ingest.convert.vision import FakeVision, shrink_for_vision
from ingest.core import keys
from ingest.core.config import Settings
from ingest.core.db import session_factory
from ingest.core.models import OcrBatch
from ingest.core.storage import MemoryStorage

GOOD = (
    "Các thành viên Ban Kiểm soát của Ngân hàng trong kỳ và vào ngày lập báo cáo "
    "tài chính riêng như sau. Bà Kim Ly Huyên là Trưởng Ban Kiểm soát chuyên trách. "
) * 3
BAD = GOOD.replace("viên", "vién").replace("Kiểm", "Kiém").replace("tài", "tàì")


def noise_png(w=160, h=80, seed=1) -> bytes:
    rnd = random.Random(seed)
    samples = bytes(rnd.randrange(256) for _ in range(w * h * 3))
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, samples, False).tobytes("png")


@pytest.mark.parametrize(
    ("word", "ok"),
    [("viên", True), ("vién", False), ("Thịnh", True), ("Vượng", True), ("gì", True),
     ("giữa", True), ("quản", True), ("nghĩa", True), ("tiép", False), ("THUYÉT", False)],
)  # fmt: skip
def test_vietnamese_syllables(word, ok):
    assert is_valid(word) is ok


def test_bad_diacritic_ratio_ignores_abbrev_and_plain_words():
    assert bad_diacritic_ratio(GOOD)[0] == 0
    assert bad_diacritic_ratio("Theo QĐ của HĐQT, Yasunori Takahashi ký")[0] == 0
    assert bad_diacritic_ratio(BAD)[0] > 0.1


def test_vision_reason_v1_vs_v2():
    assert vision_reason(GOOD, 0.95, 0.6, None, 2) is None
    assert vision_reason(BAD, 0.95, 0.6, None, 1) is None  # v1 không bắt sai dấu
    assert vision_reason(BAD, 0.95, 0.6, None, 2).startswith("sai dấu")
    table = "Cho vay khách hàng 1.085.310.056 832.975.811 Tiền gửi 42.381.695 30.178.861"
    assert vision_reason(table, 0.9, 0.6, None, 1).startswith("nhiều số")
    assert vision_reason(GOOD, 0.3, 0.6).startswith("OCR tin cậy thấp")


def test_shrink_for_vision_makes_smaller_jpeg():
    big = noise_png(3000, 1500)
    out = shrink_for_vision(big, max_side=1800)
    assert out[:2] == b"\xff\xd8" and len(out) < len(big)
    pix = pymupdf.Pixmap(out)
    assert max(pix.width, pix.height) == 1800
    assert shrink_for_vision(b"not an image") == b"not an image"


class Flaky:
    """Trả 429 n lần rồi mới trả lời; ghi lại ảnh đã nhận."""

    def __init__(self, fails: int, code: int = 429) -> None:
        self.fails, self.code, self.calls, self.images = fails, code, 0, []

    def describe(self, png: bytes) -> str:
        self.calls += 1
        self.images.append(png)
        if self.calls <= self.fails:
            req = httpx.Request("POST", "http://x/chat/completions")
            raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(self.code))
        return "| Khu vực | % |\n|---|---|\n| Miền Bắc | 38 |"


def make_acts(ocr_text: str, vision):
    st = MemoryStorage()
    st.put("raw/d/a.png", noise_png(2400, 1200))
    acts = ConvertActivities(st, FakeOcr(ocr_text, 0.95), vision=vision)
    acts.vision_retry_delays = (0, 0, 0)
    return st, acts


async def run_image(acts, version: int, idx: int = 0):
    batch = OcrBatch("d", [0], idx, "raw/d/a.png", "image", version)
    await ActivityEnvironment().run(acts.ocr_pages, batch)
    return acts.storage.get(keys.md_raw_ocr_key("d", idx)).decode()


async def test_v2_retries_429_then_uses_vision(caplog):
    vision = Flaky(fails=2)
    st, acts = make_acts("Doanh thu\nT1\nT2\nT3", vision)
    with caplog.at_level(logging.INFO, logger="ingest.convert.activities"):
        md = await run_image(acts, 2)
    assert vision.calls == 3 and "| Miền Bắc | 38 |" in md
    assert vision.images[0][:2] == b"\xff\xd8"  # đã thu nhỏ thành JPEG
    logs = caplog.text
    assert logs.count("VLM lỗi") == 2 and "VLM ok" in logs and "ít chữ" in logs


async def test_v1_gives_up_on_first_429_and_sends_original_png():
    vision = Flaky(fails=1)
    st, acts = make_acts("Doanh thu\nT1\nT2\nT3", vision)
    md = await run_image(acts, 1)
    assert vision.calls == 1 and "Miền Bắc" not in md and "T1" in md
    assert vision.images[0][:4] == b"\x89PNG"


async def test_v2_gives_up_after_all_retries_and_keeps_ocr():
    vision = Flaky(fails=10, code=503)
    st, acts = make_acts("Doanh thu\nT1\nT2\nT3", vision)
    md = await run_image(acts, 2)
    assert vision.calls == 4 and "T1" in md


async def test_v2_sends_bad_diacritic_page_v1_keeps_ocr(caplog):
    vision = FakeVision("Đoạn văn đọc lại bằng VLM")
    st, acts = make_acts(BAD, vision)
    assert "vién" in await run_image(acts, 1, 0) and vision.calls == 0
    with caplog.at_level(logging.INFO, logger="ingest.convert.activities"):
        assert "đọc lại bằng VLM" in await run_image(acts, 2, 1)
    assert vision.calls == 1 and "sai dấu" in caplog.text


async def test_ocr_decision_is_logged(caplog):
    st, acts = make_acts(GOOD, FakeVision())
    with caplog.at_level(logging.INFO, logger="ingest.convert.activities"):
        await run_image(acts, 2)
    assert "OCR | d trang 1 | v2" in caplog.text


class Wf:
    def __init__(self):
        self.ingests = []

    async def start_ingest(self, inp):
        self.ingests.append(inp)


def test_api_three_profiles_have_own_ids():
    wf = Wf()
    client = TestClient(create_app(MemoryStorage(), session_factory("sqlite:///:memory:"), wf,
                                   Settings(max_upload_bytes=10_000)))  # fmt: skip
    data = b"Ghi chu thu nghiem ba che do xu ly tai lieu."
    got = {}
    for prof, form in [("v2", {}), ("v1", {"pipeline_version": "1"}),
                       ("legacy", {"extract_media": "false"})]:  # fmt: skip
        r = client.post("/documents", files={"file": ("a.txt", data)}, data=form).json()
        assert r["profile"] == prof and not r["duplicate"]
        got[prof] = r["doc_id"]
    assert got["v2"] == compute_doc_id(data) and got["v1"].startswith("v1-")
    assert len(set(got.values())) == 3 and all(len(i) == 64 for i in got.values())
    assert [i.pipeline_version for i in wf.ingests] == [2, 1, 2]
    assert profile_of(got["legacy"]) == "legacy"
    bad = client.post("/documents", files={"file": ("a.txt", data)}, data={"pipeline_version": "3"})
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("body", "too_long"),
    [
        ('{"error":{"message":"This model\'s maximum context length is 8192 tokens"}}', True),
        ('{"error":"input length exceeds the context length"}', True),
        ('{"error":{"message":"Post \\"http://127.0.0.1:56006/tokenize\\": dial tcp '
         '127.0.0.1:56006: connect: connection reset by peer"}}', False),
        ('{"error":"invalid token in request"}', False),
    ],
)  # fmt: skip
def test_embedder_only_non_retryable_when_really_too_long(body, too_long):
    from ingest.index.embedder import _is_too_long

    assert _is_too_long(body) is too_long
