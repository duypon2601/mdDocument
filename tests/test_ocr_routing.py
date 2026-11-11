"""OCR tiếng Việt (Tesseract) và phân loại ảnh tài liệu / chart để chọn OCR hay Vision."""

import os
import random

import pymupdf
import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from ingest.convert.activities import ConvertActivities
from ingest.convert.ocr import FakeOcr, TesseractOcrEngine, parse_tsv
from ingest.convert.parsers import image_kind
from ingest.convert.vision import FakeVision
from ingest.core import keys
from ingest.core.models import OcrBatch
from ingest.core.storage import MemoryStorage

DOC_TEXT = "\n".join(
    [
        "Điều 3. Giá trị hợp đồng và phương thức thanh toán của hai bên",
        "3.1. Tổng giá trị hợp đồng đã bao gồm thuế giá trị gia tăng mười phần trăm",
        "3.2. Bên A thanh toán cho Bên B làm hai đợt bằng hình thức chuyển khoản",
    ]
)
CHART_TEXT = "Doanh thu\nT1\nT2\nT3\nTriệu đồng\nChi phí"


def png(color: tuple[int, int, int], w: int = 200, h: int = 100) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


def noise_png(seed: int = 1) -> bytes:
    rnd = random.Random(seed)
    w, h = 160, 80
    samples = bytes(rnd.randrange(256) for _ in range(w * h * 3))
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, samples, False).tobytes("png")


WHITE, BLUE = png((255, 255, 255)), png((30, 90, 200))


def test_document_text_is_not_graphic_even_with_color():
    assert not image_kind.is_graphic(DOC_TEXT, WHITE)
    assert not image_kind.is_graphic(DOC_TEXT, BLUE)  # con dấu, nền màu: dòng vẫn dài


@pytest.mark.parametrize(
    ("text", "image"),
    [
        (CHART_TEXT, WHITE),  # nhãn ngắn: sơ đồ, chart đen trắng
        ("NV001 15.000.000 2.000.000 17.000.000\n" * 4, WHITE),  # bảng số
        ("", WHITE),  # không có chữ: ảnh chụp, logo
    ],
)
def test_graphic_cases(text, image):
    assert image_kind.is_graphic(text, image)


def test_colored_short_lines_is_chart():
    text = "Cơ cấu doanh thu theo khu vực\nMiền Bắc 38%\nMiền Nam 35%\nXuất khẩu 10%"
    assert image_kind.is_graphic(text, BLUE)
    assert image_kind.color_ratio(BLUE) == 1.0 and image_kind.color_ratio(WHITE) == 0.0
    assert image_kind.color_ratio(b"not an image") == 0.0


def test_parse_tsv_keeps_lines_paragraphs_and_conf():
    head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tl\tt\tw\th\tconf\ttext"
    rows = [
        "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t96\tĐiều",
        "5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t90\t3.",
        "5\t1\t1\t1\t2\t1\t0\t0\t1\t1\t80\tGiá",
        "4\t1\t1\t1\t2\t0\t0\t0\t1\t1\t-1\t",
        "5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t-1\t ",
        "5\t1\t2\t1\t1\t2\t0\t0\t1\t1\t70\tBên",
    ]
    text, conf = parse_tsv("\n".join([head, *rows]))
    assert text == "Điều 3.\nGiá\n\nBên"
    assert conf == pytest.approx((0.96 + 0.90 + 0.80 + 0.70) / 4)
    assert parse_tsv(head) == ("", 1.0)


def test_tesseract_unavailable_raises_non_retryable():
    eng = TesseractOcrEngine(lang="khong_co_ngon_ngu_nay")
    assert not eng.available()
    with pytest.raises(ApplicationError) as ei:
        eng.recognize(WHITE)
    assert ei.value.type == "OCR_UNAVAILABLE" and ei.value.non_retryable


@pytest.mark.skipif(
    "vie" not in __import__("ingest.convert.ocr", fromlist=["x"]).tesseract_langs(),
    reason="máy chưa cài tesseract + gói vie",
)
def test_tesseract_reads_vietnamese_diacritics():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=200)
    font = next(
        (f for f in ["/System/Library/Fonts/Supplemental/Arial.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if os.path.exists(f)),
        None,
    )  # fmt: skip
    if font is None:
        pytest.skip("không có font tiếng Việt để vẽ ảnh thử")
    page.insert_font(fontname="vn", fontfile=font)
    page.insert_text((20, 80), "Hợp đồng thanh toán đợt hai", fontname="vn", fontsize=28)
    img = page.get_pixmap(dpi=200).tobytes("png")
    text, conf = TesseractOcrEngine().recognize(img)
    assert "Hợp đồng" in text and "đợt" in text and conf > 0.6


async def test_pdf_scan_chart_page_goes_to_vision_document_page_stays_ocr():
    st = MemoryStorage()
    st.put("raw/p/a.png", noise_png())
    vision = FakeVision("| Khu vực | % |\n|---|---|\n| Miền Bắc | 38 |")
    env = ActivityEnvironment()

    acts = ConvertActivities(st, FakeOcr(CHART_TEXT, 0.95), vision=vision)
    await env.run(acts.ocr_pages, OcrBatch("p", [0], 0, "raw/p/a.png", "image"))
    assert "| Miền Bắc | 38 |" in st.get(keys.md_raw_ocr_key("p", 0)).decode()

    acts = ConvertActivities(st, FakeOcr(DOC_TEXT, 0.95), vision=vision)
    await env.run(acts.ocr_pages, OcrBatch("p", [0], 1, "raw/p/a.png", "image"))
    assert "Điều 3." in st.get(keys.md_raw_ocr_key("p", 1)).decode()
    assert vision.calls == 1
