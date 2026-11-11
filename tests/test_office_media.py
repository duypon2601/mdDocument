"""Ảnh trên trang PDF có chữ, bảng xlsx sạch, chart gốc trong docx/pptx, OCR ảnh pptx."""

import io
import random
import zipfile

import pymupdf
from openpyxl import Workbook
from temporalio.testing import ActivityEnvironment

from ingest.convert.activities import ConvertActivities
from ingest.convert.ocr import FakeOcr
from ingest.convert.parsers import docx_charts, pdf, pptx_media, xlsx_tables
from ingest.convert.vision import FakeVision
from ingest.core import keys
from ingest.core.models import FinalizeInput, IngestInput, OcrBatch
from ingest.core.storage import MemoryStorage

TEXT = "Doanh thu quy mot tang deu qua cac thang, chi phi giu on dinh. " * 3  # font helv không dấu


def noise_png(w: int = 400, h: int = 240, seed: int = 1) -> bytes:
    rnd = random.Random(seed)
    samples = bytes(rnd.randrange(256) for _ in range(w * h * 3))
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, samples, False).tobytes("png")


def setup(data: bytes, name: str, ocr=None, vision=None):
    st = MemoryStorage()
    rk = keys.raw_key("d1", name)
    st.put(rk, data)
    acts = ConvertActivities(st, ocr or FakeOcr(), pages_per_batch=2, vision=vision)
    return st, acts, IngestInput(doc_id="d1", file_name=name, raw_key=rk)


async def run_all(st, acts, inp) -> tuple[str, list[list[int]]]:
    env = ActivityEnvironment()
    info = await env.run(acts.detect_format, inp)
    part = await env.run(acts.parse_document, inp)
    for i, pages in enumerate(info.ocr_page_batches):
        await env.run(acts.ocr_pages, OcrBatch(inp.doc_id, pages, i, inp.raw_key, info.kind))
    fin = FinalizeInput(
        inp.doc_id, inp.file_name, list(range(len(info.ocr_page_batches))), part.page_count
    )
    res = await env.run(acts.finalize_markdown, fin)
    return st.get(res.md_key).decode(), info.ocr_page_batches


# ---------- PDF: trang vừa chữ vừa ảnh ----------


def make_mixed_pdf(logo: bool = False) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 200), "Mo dau. " + TEXT, fontsize=11)
    page.insert_image(pymupdf.Rect(50, 220, 500, 500), stream=noise_png())
    if logo:  # ảnh nhỏ dưới 1 inch: bỏ qua
        page.insert_image(pymupdf.Rect(500, 20, 540, 50), stream=noise_png(80, 60, 2))
    page.insert_textbox(pymupdf.Rect(50, 540, 550, 700), "Ket luan. " + TEXT, fontsize=11)
    return doc.tobytes()


def test_list_figures_skips_small_images():
    doc = pdf.open_pdf(make_mixed_pdf(logo=True))
    figures = pdf.list_figures(doc, [0])
    assert len(figures) == 1
    page, rect = figures[0]
    assert page == 0 and rect.width > 400


async def test_pdf_chart_on_text_page_goes_to_vision_and_lands_in_place():
    vision = FakeVision("| Tháng | Doanh thu |\n|---|---|\n| T1 | 1250 |")
    st, acts, inp = setup(make_mixed_pdf(), "a.pdf", ocr=FakeOcr("12 34", 0.9), vision=vision)
    md, batches = await run_all(st, acts, inp)
    assert batches == [[1]]  # trang 0 có chữ, chỉ hình (1 = page_count + 0) đi OCR
    assert vision.calls == 1
    assert "picture text" not in md and "<!--" not in md.replace("<!-- page: 1 -->", "")
    assert md.index("Mo dau") < md.index("| T1 | 1250 |") < md.index("Ket luan")


# ---------- xlsx: bảng sạch ----------


def make_tables_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Doanh thu"
    ws["A1"], ws["B1"] = "Thuế suất VAT", 0.1
    ws.append([])
    ws.append(["Mã SP", "Đơn giá", "Số lượng", None, "Tháng", "Doanh thu"])
    ws.append(["SP01", 200000, 33, None, "T1", 1250])
    ws.append(["SP02", 225000, None, None, "T2", 1380])
    ws["A8"], ws["B8"] = "Tổng", 425000
    ws["A9"], ws["B9"] = "Trung bình", 212500.5
    ws2 = wb.create_sheet("Năm")
    ws2.append(["Quý", 2024, 2025])
    ws2.append(["Q1", 10, 12])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_tables_split_side_by_side_and_no_nan():
    md = xlsx_tables.workbook_markdown(make_tables_xlsx())
    assert "NaN" not in md and "Unnamed" not in md
    assert "Thuế suất VAT: 0.1" in md
    assert "| Mã SP | Đơn giá | Số lượng |" in md
    assert "| SP02 | 225000 |  |" in md
    assert "| Tháng | Doanh thu |" in md and "| T2 | 1380 |" in md
    assert "Tổng: 425000" in md and "Trung bình: 212500.5" in md
    assert "| Quý | 2024 | 2025 |" in md  # năm vẫn là tiêu đề


async def test_xlsx_pipeline_uses_clean_tables():
    st, acts, inp = setup(make_tables_xlsx(), "a.xlsx")
    md, _ = await run_all(st, acts, inp)
    assert "## Doanh thu" in md and "| Tháng | Doanh thu |" in md and "NaN" not in md


# ---------- pptx: ảnh OCR và chart gốc ----------


def make_pptx() -> bytes:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[5])
    s1.shapes.title.text = "Kết quả kinh doanh"
    s1.shapes.add_picture(io.BytesIO(noise_png()), Inches(1), Inches(2), Inches(4))
    data = CategoryChartData()
    data.categories = ["Q1", "Q2"]
    data.add_series("Doanh thu", (10, 15))
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Biểu đồ"
    s2.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(2), Inches(6), Inches(4), data
    )
    xy = XyChartData()
    ser = xy.add_series("Giá")
    ser.add_data_point(1.5, 20)
    ser.add_data_point(2.5, 30)
    s2.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, Inches(1), Inches(6), Inches(6), Inches(1), xy)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_pptx_markdown_has_image_marker_and_chart_tables():
    md = pptx_media.to_markdown(make_pptx())
    assert "# Kết quả kinh doanh" in md
    assert "<!-- image: ppt/media/image" in md
    assert "### Biểu đồ 1 (slide 2)" in md and "| Q2 | 15 |" in md
    assert "Loại: phân tán" in md and "| 2.5 | 30 |" in md  # MarkItDown: [unsupported chart]


async def test_pptx_image_is_ocred_and_placed_on_its_slide():
    ocr = FakeOcr("Hoá đơn số 0012 ngày 03/10/2025 tổng cộng thanh toán đủ. " * 2, 0.95)
    st, acts, inp = setup(make_pptx(), "a.pptx", ocr=ocr)
    md, batches = await run_all(st, acts, inp)
    assert batches == [[0]] and ocr.calls == 1
    assert "<!-- image:" not in md
    assert md.index("Kết quả kinh doanh") < md.index("Hoá đơn số 0012") < md.index("Biểu đồ 1")


# ---------- docx: chart gốc ----------

C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CHART_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"
CHART_CT = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"


def make_docx_with_chart() -> bytes:
    """python-docx không tạo chart: ghép chart XML (sinh bằng python-pptx) vào docx."""
    import docx
    from pptx.chart.data import CategoryChartData
    from pptx.chart.xmlwriter import ChartXmlWriter
    from pptx.enum.chart import XL_CHART_TYPE

    d = docx.Document()
    d.add_paragraph("Đoạn trước biểu đồ.")
    d.add_paragraph("CHART_HERE")
    d.add_paragraph("Đoạn sau biểu đồ.")
    buf = io.BytesIO()
    d.save(buf)

    data = CategoryChartData()
    data.categories = ["T1", "T2"]
    data.add_series("Chi phí", (980, 1040))
    chart_xml = ChartXmlWriter(XL_CHART_TYPE.LINE, data).xml.encode()
    drawing = (
        '<w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/'
        'drawingml/2006/wordprocessingDrawing"><wp:extent cx="5000000" cy="3000000"/>'
        '<wp:docPr id="9" name="Chart 1"/><a:graphic xmlns:a="http://schemas.openxmlformats'
        '.org/drawingml/2006/main"><a:graphicData uri="' + C_NS + '">'
        f'<c:chart xmlns:c="{C_NS}" xmlns:r="{R_NS}" r:id="rIdChart1"/>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
    )

    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for info in src.infolist():
            raw = src.read(info)
            if info.filename == "word/document.xml":
                raw = raw.decode().replace("<w:r><w:t>CHART_HERE</w:t></w:r>", drawing).encode()
            elif info.filename == "word/_rels/document.xml.rels":
                rel = f'<Relationship Id="rIdChart1" Type="{CHART_REL}" '
                rel += 'Target="charts/chart1.xml"/>'
                raw = raw.replace(b"</Relationships>", rel.encode() + b"</Relationships>")
            elif info.filename == "[Content_Types].xml":
                ov = f'<Override PartName="/word/charts/chart1.xml" ContentType="{CHART_CT}"/>'
                raw = raw.replace(b"</Types>", ov.encode() + b"</Types>")
            w.writestr(info, raw)
        w.writestr("word/charts/chart1.xml", chart_xml)
    return out.getvalue()


def test_docx_chart_tokenized_in_place():
    data = make_docx_with_chart()
    tokenized, charts = docx_charts.tokenize_charts(data)
    assert len(charts) == 1 and "| T2 | 1040 |" in charts[0]
    assert b"QXCHART0000QX" in zipfile.ZipFile(io.BytesIO(tokenized)).read("word/document.xml")


async def test_docx_chart_lands_between_paragraphs():
    st, acts, inp = setup(make_docx_with_chart(), "a.docx")
    md, _ = await run_all(st, acts, inp)
    assert "QXCHART" not in md
    assert md.index("Đoạn trước") < md.index("| T2 | 1040 |") < md.index("Đoạn sau")


def test_fill_tokens_appends_lost_chart():
    assert docx_charts.fill_tokens("Văn bản", ["### Biểu đồ 1"]) == "Văn bản\n\n### Biểu đồ 1"
