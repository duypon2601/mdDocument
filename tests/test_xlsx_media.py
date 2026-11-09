"""File Excel có biểu đồ và ảnh nhúng: chart thành bảng Markdown, ảnh đi OCR/Vision."""

import io
import random

import pymupdf
from defusedxml import ElementTree as ET
from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.drawing.image import Image as XlImage
from temporalio.testing import ActivityEnvironment

from ingest.convert.activities import ConvertActivities
from ingest.convert.ocr import FakeOcr
from ingest.convert.parsers import xlsx_media
from ingest.convert.vision import FakeVision
from ingest.core import keys
from ingest.core.models import FinalizeInput, IngestInput, OcrBatch
from ingest.core.storage import MemoryStorage

LONG_TEXT = "Bảng kê chi phí vận chuyển tháng 10 được chụp từ phần mềm kế toán. " * 4


def noise_png(w: int = 160, h: int = 80, seed: int = 1) -> bytes:
    rnd = random.Random(seed)
    samples = bytes(rnd.randrange(256) for _ in range(w * h * 3))
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, samples, False).tobytes("png")


def make_xlsx(chart: bool = True, images: int = 0) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Doanh thu"
    ws.append(["Quý", "2024", "2025"])
    for row in [["Q1", 10, 12], ["Q2", 15, 18], ["Q3", 20, 25]]:
        ws.append(row)
    if chart:
        bar = BarChart()
        bar.title = "Doanh thu theo quý"
        bar.add_data(
            Reference(ws, min_col=2, max_col=3, min_row=1, max_row=4), titles_from_data=True
        )
        bar.set_categories(Reference(ws, min_col=1, min_row=2, max_row=4))
        ws.add_chart(bar, "E2")
    ws2 = wb.create_sheet("Ảnh chụp")
    ws2["A1"] = "Phụ lục"
    for i in range(images):
        ws2.add_image(XlImage(io.BytesIO(noise_png(seed=i + 1))), f"B{3 + i * 10}")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def setup(data: bytes, ocr=None, vision=None, mode="auto"):
    st = MemoryStorage()
    rk = keys.raw_key("x1", "a.xlsx")
    st.put(rk, data)
    acts = ConvertActivities(
        st, ocr or FakeOcr(), pages_per_batch=2, vision=vision, docx_image_mode=mode
    )
    return st, acts, IngestInput(doc_id="x1", file_name="a.xlsx", raw_key=rk)


async def run_all(st, acts, inp) -> str:
    env = ActivityEnvironment()
    info = await env.run(acts.detect_format, inp)
    await env.run(acts.parse_document, inp)
    for i, pages in enumerate(info.ocr_page_batches):
        await env.run(acts.ocr_pages, OcrBatch(inp.doc_id, pages, i, inp.raw_key, info.kind))
    fin = FinalizeInput(inp.doc_id, inp.file_name, list(range(len(info.ocr_page_batches))))
    res = await env.run(acts.finalize_markdown, fin)
    return st.get(res.md_key).decode()


def test_chart_from_cell_range_becomes_table():
    # openpyxl không ghi cache vào chart, nên đây là đường đọc vùng ô
    md = xlsx_media.charts_markdown(make_xlsx())
    assert "### Biểu đồ 1 (sheet Doanh thu, ô E2): Doanh thu theo quý" in md
    assert "| Hạng mục | 2024 | 2025 |" in md
    assert "| Q2 | 15 | 18 |" in md
    assert "Loại: cột/thanh" in md


def test_chart_cache_used_without_reading_cells():
    xml = """<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:chart>
      <c:title><c:tx><c:rich><a:p><a:r><a:t>Thị phần</a:t></a:r></a:p></c:rich></c:tx></c:title>
      <c:plotArea><c:pieChart><c:ser>
        <c:tx><c:v>2025</c:v></c:tx>
        <c:cat><c:strRef><c:f>S!$A$1:$A$2</c:f><c:strCache><c:ptCount val="2"/>
          <c:pt idx="0"><c:v>Miền Bắc</c:v></c:pt><c:pt idx="1"><c:v>Miền | Nam</c:v></c:pt>
        </c:strCache></c:strRef></c:cat>
        <c:val><c:numRef><c:f>S!$B$1:$B$2</c:f><c:numCache><c:ptCount val="2"/>
          <c:pt idx="1"><c:v>0.6</c:v></c:pt>
        </c:numCache></c:numRef></c:val>
      </c:ser></c:pieChart></c:plotArea></c:chart></c:chartSpace>"""

    class NoCells(xlsx_media._CellResolver):
        def values(self, formula):
            raise AssertionError("không được đọc ô khi đã có cache")

    md = xlsx_media.chart_markdown(ET.fromstring(xml), NoCells(b""), "Biểu đồ 1")
    assert md.startswith("### Biểu đồ 1: Thị phần")
    assert "| Miền Bắc |  |" in md and "| Miền \\| Nam | 0.6 |" in md
    assert "Loại: tròn" in md


def test_pie_and_multiple_charts_numbered():
    wb = Workbook()
    ws = wb.active
    for r in [["A", 1], ["B", 2]]:
        ws.append(r)
    for anchor in ("D1", "D20"):
        pie = PieChart()
        pie.add_data(Reference(ws, min_col=2, min_row=1, max_row=2))
        pie.set_categories(Reference(ws, min_col=1, min_row=1, max_row=2))
        ws.add_chart(pie, anchor)
    buf = io.BytesIO()
    wb.save(buf)
    md = xlsx_media.charts_markdown(buf.getvalue())
    assert "Biểu đồ 1 (sheet Sheet, ô D1)" in md and "Biểu đồ 2 (sheet Sheet, ô D20)" in md


def test_list_images_order_anchor_and_filter():
    data = make_xlsx(chart=False, images=3)
    imgs = xlsx_media.list_images(data)
    assert [(i.sheet, i.anchor) for i in imgs] == [("Ảnh chụp", "B3"), ("Ảnh chụp", "B13"),
                                                   ("Ảnh chụp", "B23")]  # fmt: skip
    assert xlsx_media.list_images(data, min_bytes=10**8) == []
    assert xlsx_media.list_images(b"not a zip") == []


async def test_detect_fast_path_without_images():
    _, acts, inp = setup(make_xlsx())
    info = await ActivityEnvironment().run(acts.detect_format, inp)
    assert info.kind == "xlsx" and info.ocr_page_batches == []


async def test_full_flow_chart_and_images_ocr():
    st, acts, inp = setup(make_xlsx(images=3), ocr=FakeOcr(LONG_TEXT))
    info = await ActivityEnvironment().run(acts.detect_format, inp)
    assert info.ocr_page_batches == [[0, 1], [2]]
    md = await run_all(st, acts, inp)
    assert "| Q1 | 10 | 12 |" in md  # bảng gốc từ MarkItDown
    assert "## Biểu đồ trong file" in md
    assert "### Ảnh 3 (sheet Ảnh chụp, ô B23)" in md
    assert md.count("Bảng kê chi phí vận chuyển") == 12  # 3 ảnh x 4 câu


async def test_chart_screenshot_goes_to_vision():
    ocr = FakeOcr("2023 2024 10 20", 0.9)  # ít chữ, nhiều số: kiểu biểu đồ chụp
    vision = FakeVision("| Năm | Lãi |\n|---|---|\n| 2024 | 20 |")
    st, acts, inp = setup(make_xlsx(chart=False, images=1), ocr=ocr, vision=vision)
    md = await run_all(st, acts, inp)
    assert vision.calls == 1 and "| 2024 | 20 |" in md and "2023 2024 10 20" not in md


async def test_empty_ocr_image_adds_no_block():
    st, acts, inp = setup(make_xlsx(chart=False, images=1), ocr=FakeOcr(""))
    md = await run_all(st, acts, inp)
    assert "### Ảnh" not in md and "Phụ lục" in md


def make_formula_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Lương"
    ws.append(["Tên", "Lương", "Thưởng", "Tổng"])
    for i, (a, b) in enumerate([(10, 1), (20, 2), (30, 3)], start=2):
        ws.append(["NV", a, b, f"=B{i}+C{i}"])
    ws["D6"] = "=SUM(D2:D4)"
    ws["E2"] = "=LOG10(B2)*$B$2"
    ws["F2"] = '=IF(A2="x|y",1,0)'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_formulas_verbatim_and_fill_down_grouped():
    md = xlsx_media.formulas_markdown(make_formula_xlsx())
    assert md.startswith("## Công thức trong file\n\n### Sheet Lương")
    assert "| D2:D4 | `=B2+C2` (kéo xuống 3 ô) |" in md
    assert "| D6 | `=SUM(D2:D4)` |" in md
    assert "| E2 | `=LOG10(B2)*$B$2` |" in md  # LOG10 không bị coi là ô
    assert '`=IF(A2="x\\|y",1,0)`' in md


def test_formulas_none_and_limit():
    assert xlsx_media.formulas_markdown(make_xlsx(chart=False)) == ""
    assert xlsx_media.formulas_markdown(b"not a zip") == ""
    md = xlsx_media.formulas_markdown(make_formula_xlsx(), max_rows=1)
    assert md.count("| `") == 1 and "Chỉ liệt kê 1 dòng" in md


def test_formula_cached_value_shown():
    # openpyxl không tính công thức; giả lập file đã mở bằng Excel bằng cách chèn <v>
    import zipfile

    src = make_formula_xlsx()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            body = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                body = body.replace(b"<f>SUM(D2:D4)</f><v></v>", b"<f>SUM(D2:D4)</f><v>66</v>")
                body = body.replace(b"<f>SUM(D2:D4)</f></c>", b"<f>SUM(D2:D4)</f><v>66</v></c>")
            zout.writestr(item, body)
    md = xlsx_media.formulas_markdown(out.getvalue())
    assert "| D6 | `=SUM(D2:D4)` | 66 |" in md


async def test_parse_document_appends_formulas_unless_disabled():
    env = ActivityEnvironment()
    st, acts, inp = setup(make_formula_xlsx())
    await env.run(acts.parse_document, inp)
    assert "=SUM(D2:D4)" in st.get(keys.md_raw_text_key("x1")).decode()
    acts.xlsx_formulas = False
    await env.run(acts.parse_document, inp)
    assert "Công thức trong file" not in st.get(keys.md_raw_text_key("x1")).decode()


async def test_legacy_mode_skips_charts_formulas_images():
    from dataclasses import replace

    env = ActivityEnvironment()
    st, acts, inp = setup(make_xlsx(images=2))
    inp = replace(inp, extract_media=False)
    info = await env.run(acts.detect_format, inp)
    assert info.ocr_page_batches == []
    await env.run(acts.parse_document, inp)
    md = st.get(keys.md_raw_text_key("x1")).decode()
    assert "| Q1 | 10 | 12 |" in md and "Biểu đồ" not in md
