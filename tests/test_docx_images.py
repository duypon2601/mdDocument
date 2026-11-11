"""Luồng file Word có ảnh: fast-path, OCR/Vision theo từng ảnh, chèn nội dung về đúng chỗ."""

import io
import random

import docx
import pymupdf
import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from ingest.convert.activities import ConvertActivities, vision_reason
from ingest.convert.ocr import FakeOcr
from ingest.convert.parsers import docx_images
from ingest.convert.vision import FakeVision, OpenAICompatVision
from ingest.core import keys
from ingest.core.models import FinalizeInput, OcrBatch
from ingest.core.storage import MemoryStorage

LONG_TEXT = "Đây là đoạn văn bản dài được chụp lại từ một trang tài liệu scan. " * 5


def noise_png(w: int = 160, h: int = 80, seed: int = 1) -> bytes:
    """Ảnh nhiễu để file đủ lớn (> 2KB) sau khi nén PNG."""
    rnd = random.Random(seed)
    samples = bytes(rnd.randrange(256) for _ in range(w * h * 3))
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, samples, False).tobytes("png")


def make_docx(*images: bytes, repeat_first: bool = False) -> bytes:
    d = docx.Document()
    d.add_paragraph("Đoạn mở đầu")
    for i, img in enumerate(images):
        d.add_picture(io.BytesIO(img))
        d.add_paragraph(f"Sau ảnh {i + 1}")
    if repeat_first and images:
        d.add_picture(io.BytesIO(images[0]))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def setup(data: bytes, ocr=None, vision=None, mode="auto"):
    st = MemoryStorage()
    rk = keys.raw_key("d1", "a.docx")
    st.put(rk, data)
    acts = ConvertActivities(
        st, ocr or FakeOcr(), pages_per_batch=2, vision=vision, docx_image_mode=mode
    )
    from ingest.core.models import IngestInput

    return st, acts, IngestInput(doc_id="d1", file_name="a.docx", raw_key=rk)


async def run_all(st, acts, inp) -> str:
    env = ActivityEnvironment()
    info = await env.run(acts.detect_format, inp)
    part = await env.run(acts.parse_document, inp)
    batches = []
    for i, pages in enumerate(info.ocr_page_batches):
        r = await env.run(acts.ocr_pages, OcrBatch("d1", pages, i, inp.raw_key, info.kind))
        batches.append(r.batch_index)
    fin = FinalizeInput("d1", "a.docx", batches, part.page_count)
    await env.run(acts.finalize_markdown, fin)
    return st.get(keys.md_key("d1")).decode()


async def test_docx_without_media_takes_fast_path():
    _, acts, inp = setup(make_docx())
    info = await ActivityEnvironment().run(acts.detect_format, inp)
    assert info.kind == "docx" and info.ocr_page_batches == []


async def test_detect_lists_images_skips_tiny_and_duplicates():
    tiny = noise_png(8, 8)
    data = make_docx(noise_png(seed=1), tiny, noise_png(seed=2), noise_png(seed=3),
                     repeat_first=True)  # fmt: skip
    _, acts, inp = setup(data)
    info = await ActivityEnvironment().run(acts.detect_format, inp)
    # slot 1 (ảnh nhỏ) và slot 4 (ảnh 1 lặp lại) bị bỏ; batch 2 ảnh
    assert info.ocr_page_batches == [[0, 2], [3]]


async def test_text_image_uses_ocr_and_lands_in_place():
    ocr = FakeOcr(LONG_TEXT, 0.95)
    vision = FakeVision()
    st, acts, inp = setup(make_docx(noise_png()), ocr=ocr, vision=vision)
    md = await run_all(st, acts, inp)
    assert vision.calls == 0
    assert md.index("Đoạn mở đầu") < md.index("Đây là đoạn") < md.index("Sau ảnh 1")
    assert "base64" not in md and "<!-- image" not in md


async def test_chart_image_goes_to_vision_and_becomes_table():
    ocr = FakeOcr("2023 2024 2025 120 80", 0.9)  # ít chữ, nhiều số
    vision = FakeVision("| Năm | Doanh thu |\n|---|---|\n| 2025 | 120 |")
    st, acts, inp = setup(make_docx(noise_png()), ocr=ocr, vision=vision)
    md = await run_all(st, acts, inp)
    assert vision.calls == 1
    assert md.index("Đoạn mở đầu") < md.index("| 2025 | 120 |") < md.index("Sau ảnh 1")
    assert "2023 2024" not in md


async def test_without_vision_chart_keeps_ocr_text():
    st, acts, inp = setup(make_docx(noise_png()), ocr=FakeOcr("Q1 120", 0.9))
    md = await run_all(st, acts, inp)
    assert "Q1 120" in md


async def test_vision_error_falls_back_to_ocr():
    class Broken:
        def describe(self, png):
            raise RuntimeError("429")

    st, acts, inp = setup(make_docx(noise_png()), ocr=FakeOcr("Q1 120", 0.9), vision=Broken())
    md = await run_all(st, acts, inp)
    assert "Q1 120" in md


async def test_vision_empty_keeps_ocr_caption():
    st, acts, inp = setup(make_docx(noise_png()), ocr=FakeOcr("Hình 1", 0.9), vision=FakeVision(""))
    assert "Hình 1" in await run_all(st, acts, inp)


async def test_mode_vision_skips_ocr():
    ocr = FakeOcr(LONG_TEXT)
    vision = FakeVision("VISION")
    st, acts, inp = setup(make_docx(noise_png()), ocr=ocr, vision=vision, mode="vision")
    md = await run_all(st, acts, inp)
    assert ocr.calls == 0 and "VISION" in md


async def test_mode_ocr_never_calls_vision():
    vision = FakeVision()
    st, acts, inp = setup(make_docx(noise_png()), ocr=FakeOcr("1 2"), vision=vision, mode="ocr")
    await run_all(st, acts, inp)
    assert vision.calls == 0


async def test_ocr_unavailable_uses_vision_when_configured():
    class NoOcr:
        def recognize(self, png):
            raise ApplicationError("x", type="OCR_UNAVAILABLE", non_retryable=True)

    st, acts, inp = setup(make_docx(noise_png()), ocr=NoOcr(), vision=FakeVision("VISION"))
    assert "VISION" in await run_all(st, acts, inp)


async def test_image_only_docx_is_not_empty():
    d = docx.Document()
    d.add_picture(io.BytesIO(noise_png()))
    buf = io.BytesIO()
    d.save(buf)
    st, acts, inp = setup(buf.getvalue(), ocr=FakeOcr(LONG_TEXT))
    md = await run_all(st, acts, inp)
    assert "Đây là đoạn" in md


async def test_corrupt_image_is_skipped_not_fatal():
    import zipfile

    src = make_docx(noise_png(), noise_png(seed=9))
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(out, "w") as zout:
        slots = docx_images.image_slots(src)
        for item in zin.infolist():
            body = zin.read(item.filename)
            if item.filename == slots[0]:
                body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4000  # hỏng nhưng đủ lớn
            zout.writestr(item, body)
    st, acts, inp = setup(out.getvalue(), ocr=FakeOcr(LONG_TEXT))
    md = await run_all(st, acts, inp)
    assert md.count("Đây là đoạn văn bản dài") == 5  # chỉ ảnh thứ hai


def test_placeholder_count_mismatch_appends_at_end():
    md = docx_images.mark_placeholders("A ![](data:image/png;base64...) B", ["x", "y"])
    assert "data:image" not in md
    assert docx_images.place_images(md, {"x": "IMG-X", "y": "IMG-Y"}).endswith("IMG-X\n\nIMG-Y")


@pytest.mark.parametrize(
    ("text", "conf", "expected"),
    [
        (LONG_TEXT, 0.95, False),
        ("ngắn", 0.95, True),
        (LONG_TEXT, 0.3, True),
        ("1234567890 " * 30 + LONG_TEXT[:100], 0.95, True),
    ],
)
def test_vision_reason(text, conf, expected):
    assert (vision_reason(text, conf, 0.6) is not None) is expected


def test_openai_compat_vision_request_and_fence_strip():
    import httpx

    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(req.content)
        seen["path"] = req.url.path
        msg = {"content": "```markdown\n| a |\n|---|\n```"}
        return httpx.Response(200, json={"choices": [{"message": msg}]})

    v = OpenAICompatVision("http://x/v1", "k", "gemini-2.5-flash")
    v._client = httpx.Client(base_url="http://x/v1", transport=httpx.MockTransport(handler))
    assert v.describe(b"png") == "| a |\n|---|"
    assert seen["path"] == "/v1/chat/completions"
    parts = seen["body"]["messages"][0]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
