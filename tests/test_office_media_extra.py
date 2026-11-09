"""Nhánh phụ của pptx_media, pdf, xlsx_tables, docx_charts: lỗi, trường hợp biên."""

import datetime as dt
import io
import types
import zipfile

import pymupdf
import pytest
from openpyxl import Workbook

from ingest.convert.parsers import docx_charts, pdf, pptx_media, xlsx_media, xlsx_tables
from ingest.core.errors import FILE_CORRUPTED, PASSWORD_PROTECTED, IngestError
from test_office_media import make_docx_with_chart, noise_png


def rewrite_zip(data: bytes, name: str, fn) -> bytes:
    """Đổi một member trong zip bằng fn(bytes) -> bytes (fn trả None là bỏ member)."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for info in src.infolist():
            raw = src.read(info)
            if info.filename == name:
                raw = fn(raw)
                if raw is None:
                    continue
            w.writestr(info, raw)
    return out.getvalue()


# =====================================================================
# pptx_media
# =====================================================================


def make_rich_pptx() -> bytes:
    """Slide 1: ảnh lớn có alt, ảnh nhỏ, group chứa ảnh, bảng, ghi chú.
    Slide 2: lặp lại ảnh lớn (cùng part) và một chart."""
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    big = noise_png(400, 240, 1)
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[5])
    s1.shapes.title.text = "Tổng quan"
    pic = s1.shapes.add_picture(io.BytesIO(big), Inches(1), Inches(1.5), Inches(3))
    pic._element.nvPicPr.cNvPr.set("descr", "  Biểu đồ\n doanh thu  ")
    s1.shapes.add_picture(io.BytesIO(noise_png(8, 8, 3)), Inches(5), Inches(1.5), Inches(0.3))
    grp = s1.shapes.add_group_shape()
    grp.shapes.add_picture(io.BytesIO(noise_png(300, 200, 4)), Inches(1), Inches(5), Inches(2))
    tbl = s1.shapes.add_table(3, 2, Inches(5), Inches(3), Inches(4), Inches(1)).table
    tbl.cell(0, 0).text, tbl.cell(0, 1).text = "Mục", "Giá trị"
    tbl.cell(1, 0).text, tbl.cell(1, 1).text = "a|b", "dòng 1\ndòng 2"
    # dòng 3 để trống: bị bỏ
    s1.notes_slide.notes_text_frame.text = "  Nhớ nhắc số liệu quý 3  "

    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    s2.shapes.add_picture(io.BytesIO(big), Inches(1), Inches(1), Inches(3))
    data = CategoryChartData()
    data.categories = ["Q1"]
    data.add_series("S", (1,))
    s2.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(4), Inches(4), Inches(2), data
    )
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def rich_pptx():
    return make_rich_pptx()


def test_pptx_slots_include_group_and_repeats(rich_pptx):
    slots = pptx_media.image_slots(rich_pptx)
    assert len(slots) == 4  # ảnh lớn, ảnh nhỏ, ảnh trong group, ảnh lớn lặp lại
    assert all(s.startswith("ppt/media/") for s in slots)
    assert slots[0] == slots[3]


def test_pptx_readable_slots_skip_small_and_repeats(rich_pptx):
    slots = pptx_media.image_slots(rich_pptx)
    idx = pptx_media.readable_slot_indices(rich_pptx, min_bytes=2048)
    assert 0 in idx and 3 not in idx  # lần lặp bỏ
    assert all(slots[i] != slots[1] for i in idx)  # ảnh 8x8 dưới ngưỡng
    assert len(idx) == 2


def test_pptx_markdown_table_alt_notes_group(rich_pptx):
    md = pptx_media.to_markdown(rich_pptx)
    assert md.startswith("<!-- Slide number: 1 -->")
    assert "# Tổng quan" in md
    assert "Ảnh: Biểu đồ doanh thu" in md
    assert "| Mục | Giá trị |\n| --- | --- |\n| a\\|b | dòng 1 dòng 2 |" in md
    assert "|  |  |" not in md
    assert "### Ghi chú\n\nNhớ nhắc số liệu quý 3" in md
    assert md.count("<!-- image: ppt/media/") == 4
    assert "<!-- Slide number: 2 -->" in md and "### Biểu đồ 1 (slide 2)" in md


def test_pptx_chart_error_is_skipped(rich_pptx, monkeypatch):
    def boom(*a):
        raise ValueError("chart hỏng")

    monkeypatch.setattr(xlsx_media, "chart_part_markdown", boom)
    md = pptx_media.to_markdown(rich_pptx)
    assert "Biểu đồ 1" not in md and "# Tổng quan" in md


def test_pptx_chart_empty_markdown_skipped(rich_pptx, monkeypatch):
    monkeypatch.setattr(xlsx_media, "chart_part_markdown", lambda *a: "")
    assert "Biểu đồ 1" not in pptx_media.to_markdown(rich_pptx)


def test_picture_part_edge_cases():
    no_rid = types.SimpleNamespace(_element=types.SimpleNamespace())
    assert pptx_media._picture_part(no_rid) is None

    def related_part(rid):
        raise KeyError(rid)

    broken = types.SimpleNamespace(
        _element=types.SimpleNamespace(blip_rId="rId9"),
        part=types.SimpleNamespace(related_part=related_part),
    )
    assert pptx_media._picture_part(broken) is None


def test_shape_key_none_position_first():
    s = types.SimpleNamespace
    shapes = [s(top=10, left=5), s(top=None, left=None), s(top=10, left=None)]
    assert sorted(shapes, key=pptx_media._shape_key) == [shapes[1], shapes[2], shapes[0]]


def test_table_markdown_empty_and_ragged():
    cell = types.SimpleNamespace
    row = lambda *t: types.SimpleNamespace(cells=[cell(text=x) for x in t])  # noqa: E731
    empty = types.SimpleNamespace(rows=[row("", None), row(" ")])
    assert pptx_media._table_markdown(empty) == ""
    ragged = types.SimpleNamespace(rows=[row("A", "B"), row("1")])
    assert pptx_media._table_markdown(ragged).splitlines()[-1] == "| 1 |  |"


# =====================================================================
# pdf
# =====================================================================


def test_open_pdf_corrupted():
    with pytest.raises(IngestError) as e:
        pdf.open_pdf(b"khong phai pdf")
    assert e.value.code == FILE_CORRUPTED


def test_open_pdf_password():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "bí mật")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    with pytest.raises(IngestError) as e:
        pdf.open_pdf(data)
    assert e.value.code == PASSWORD_PROTECTED


def test_open_pdf_no_pages(monkeypatch):
    fake = types.SimpleNamespace(needs_pass=False, page_count=0)
    monkeypatch.setattr(pdf.pymupdf, "open", lambda **kw: fake)
    with pytest.raises(IngestError) as e:
        pdf.open_pdf(b"%PDF")
    assert e.value.code == FILE_CORRUPTED and "không có trang" in str(e.value)


def test_classify_pages(pdf_bytes):
    doc = pdf.open_pdf(pdf_bytes(["Trang có đủ chữ để không cần OCR nhé", None, "ngắn"]))
    assert pdf.classify_pages(doc) == ([0], [1, 2])


def test_classify_pages_broken_page():
    class Page:
        def get_text(self, kind):
            raise RuntimeError("xref hỏng")

    fake = types.SimpleNamespace(page_count=1, __getitem__=None)
    fake = type("D", (), {"page_count": 1, "__getitem__": lambda self, i: Page()})()
    with pytest.raises(IngestError) as e:
        pdf.classify_pages(fake)
    assert e.value.code == FILE_CORRUPTED and "Trang 1" in str(e.value)


def test_page_markdown_and_fallback(pdf_bytes, monkeypatch):
    import pymupdf4llm

    doc = pdf.open_pdf(pdf_bytes(["Hello markdown page"]))
    assert "Hello markdown page" in pdf.page_markdown(doc, 0)

    def boom(*a, **kw):
        raise RuntimeError("layout lạ")

    monkeypatch.setattr(pymupdf4llm, "to_markdown", boom)
    assert pdf.page_markdown(doc, 0) == "Hello markdown page"


def test_render_png(pdf_bytes):
    doc = pdf.open_pdf(pdf_bytes(["x"]))
    assert pdf.render_page_png(doc, 0, dpi=36).startswith(b"\x89PNG")
    png = pdf.render_figure_png(doc, 0, (0, 0, 72, 72), dpi=72)
    assert pymupdf.Pixmap(png).width == 72
    assert pdf.figure_name(0) == "pdf-figure-1"


def test_list_figures_filters():
    doc = pymupdf.open()
    page = doc.new_page()  # 595 x 842
    big = noise_png(400, 240, 1)
    page.insert_image(pymupdf.Rect(50, 400, 300, 550), stream=big)  # hình hợp lệ
    page.insert_image(pymupdf.Rect(50, 400, 300, 550), stream=big)  # vẽ lại: trùng
    page.insert_image(pymupdf.Rect(320, 400, 560, 600), stream=noise_png(40, 40, 2))  # ít pixel
    page.insert_image(pymupdf.Rect(50, 100, 300, 250), stream=noise_png(300, 200, 3))  # trên cao
    bg = doc.new_page()
    bg.insert_image(bg.rect, stream=noise_png(300, 400, 5))  # nền phủ cả trang
    doc = pymupdf.open(stream=doc.tobytes(), filetype="pdf")

    figs = pdf.list_figures(doc, [0, 1])
    assert [p for p, _ in figs] == [0, 0]
    assert figs[0][1].y0 < figs[1][1].y0  # sắp từ trên xuống


def test_list_figures_page_error_skipped(monkeypatch):
    doc = pymupdf.open()
    doc.new_page()

    def boom(self, *a, **kw):
        raise RuntimeError("ảnh hỏng")

    monkeypatch.setattr(pymupdf.Page, "get_image_info", boom)
    assert pdf.list_figures(doc, [0]) == []


def test_cover_zero_area():
    assert pdf._cover(pymupdf.Rect(0, 0, 0, 0), pymupdf.Rect(0, 0, 10, 10)) == 0.0


def test_clean_picture_text():
    raw = "<!-- Start of picture text -->\n Q1<br>Q2 \n\n 100 <!-- End of picture text -->"
    assert pdf._clean_picture_text(raw) == "Q1\nQ2\n100"


def _fake_chunks(monkeypatch, text, boxes):
    import pymupdf4llm

    monkeypatch.setattr(
        pymupdf4llm, "to_markdown", lambda *a, **kw: [{"text": text, "page_boxes": boxes}]
    )


def test_page_markdown_with_figures_matches_and_cleans(monkeypatch):
    doc = pymupdf.open()
    doc.new_page()
    a = "Mở đầu\n"
    pic1 = "<!-- Start of picture text -->rác OCR<!-- End of picture text -->"
    mid = "\nGiữa\n"
    pic2 = "<!-- Start of picture text -->Q1<br>Q2<!-- End of picture text -->"
    end = "\nKết\n\n\n\n"
    text = a + pic1 + mid + pic2 + end
    p1 = (len(a), len(a) + len(pic1))
    p2 = (p1[1] + len(mid), p1[1] + len(mid) + len(pic2))
    boxes = [
        {"class": "picture", "pos": p1, "bbox": (0, 0, 100, 100)},
        {"class": "picture", "pos": (p1[0] + 1, p1[1]), "bbox": (0, 0, 100, 100)},  # chồng: bỏ
        {"class": "picture", "pos": p2, "bbox": (0, 300, 100, 400)},  # không khớp hình nào
        {"class": "text", "pos": (0, len(a)), "bbox": (0, 0, 1, 1)},
    ]
    _fake_chunks(monkeypatch, text, boxes)
    figures = [
        ("pdf-figure-1", pymupdf.Rect(0, 0, 100, 100)),
        ("pdf-figure-2", pymupdf.Rect(0, 600, 50, 650)),
    ]
    md = pdf.page_markdown_with_figures(doc, 0, figures)
    assert md == (
        "Mở đầu\n\n<!-- image: pdf-figure-1 -->\n\nGiữa\n\nQ1\nQ2\n\nKết\n\n"
        "<!-- image: pdf-figure-2 -->"
    )
    assert "rác OCR" not in md


def test_page_markdown_with_figures_fallback(monkeypatch, pdf_bytes):
    import pymupdf4llm

    def boom(*a, **kw):
        raise RuntimeError("lỗi")

    monkeypatch.setattr(pymupdf4llm, "to_markdown", boom)
    doc = pdf.open_pdf(pdf_bytes(["Plain text page"]))
    md = pdf.page_markdown_with_figures(doc, 0, [("pdf-figure-1", pymupdf.Rect(0, 0, 9, 9))])
    assert md == "Plain text page\n\n<!-- image: pdf-figure-1 -->"


# =====================================================================
# xlsx_tables
# =====================================================================


@pytest.mark.parametrize(
    ("v", "out"),
    [
        (None, ""),
        (True, "TRUE"),
        (False, "FALSE"),
        (3.0, "3"),
        (1e16, "1e+16"),
        (0.1 + 0.2, "0.3"),
        (dt.datetime(2025, 3, 1), "2025-03-01"),
        (dt.datetime(2025, 3, 1, 8, 30), "2025-03-01 08:30:00"),
        (dt.date(2025, 3, 1), "2025-03-01"),
        (dt.time(7, 5), "07:05:00"),
        ("  chữ  ", "chữ"),
        ("#REF!", ""),
        ("#DIV/0", ""),
        ("#N/A", ""),
        ("#hashtag", "#hashtag"),
        (42, "42"),
    ],
)
def test_text(v, out):
    assert xlsx_tables._text(v) == out


def test_col_letter():
    assert [xlsx_tables._col_letter(i) for i in (0, 25, 26, 701, 702)] == [
        "A",
        "Z",
        "AA",
        "ZZ",
        "AAA",
    ]


def test_find_regions_merges_overlapping_boxes():
    # chữ L bao quanh ô (2,1) không liền kề: hai vùng có khung chồng nhau -> gộp
    l_shape = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 3), (2, 3), (3, 3)]
    cells = {k: "x" for k in [*l_shape, (2, 1), (10, 0)]}
    regions = xlsx_tables.find_regions(cells)
    assert [sorted(r) for r in regions] == [sorted([*l_shape, (2, 1)]), [(10, 0)]]


def region(cells):
    return xlsx_tables.region_markdown(cells, list(cells))


def test_region_single_row():
    assert region({(0, 0): "Thuế", (0, 1): "0.1"}) == "Thuế: 0.1"
    assert region({(0, 0): "a", (0, 1): "b", (0, 2): "c"}) == "a | b | c"


def test_region_single_column():
    assert region({(0, 0): "Tên", (1, 0): "An"}) == "Tên: An"
    assert region({(0, 0): "1", (1, 0): "2"}) == "1\n2"
    assert region({(0, 0): "a", (1, 0): "b", (2, 0): "c"}) == "a\nb\nc"


def test_region_without_header_uses_column_letters():
    cells = {(1, 2): "1", (1, 3): "2", (2, 2): "3", (2, 3): "x|y"}
    assert region(cells) == "Bảng C2:D3:\n\n| C | D |\n| --- | --- |\n| 1 | 2 |\n| 3 | x\\|y |"


def test_region_label_rows():
    cells = {(0, 0): "Tổng", (0, 1): "10", (0, 2): "20", (1, 0): "TB", (1, 1): "5"}
    assert region(cells) == "Tổng: 10 | 20\nTB: 5"


def _xlsx(build) -> bytes:
    wb = Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_workbook_markdown_bad_file():
    assert xlsx_tables.workbook_markdown(b"khong phai xlsx") == ""


def test_workbook_markdown_empty_sheet_and_chartsheet():
    from openpyxl.chart import BarChart, Reference

    def build(wb):
        ws = wb.active
        ws.title = "Số liệu"
        ws.append(["Q1", 10])
        wb.create_sheet("Trống")
        chart = BarChart()
        chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=1))
        wb.create_chartsheet("Biểu đồ").add_chart(chart)

    md = xlsx_tables.workbook_markdown(_xlsx(build))
    assert md == "## Số liệu\n\nQ1: 10\n\n## Trống"


def test_workbook_markdown_too_large(monkeypatch):
    monkeypatch.setattr(xlsx_tables, "MAX_CELLS", 2)
    data = _xlsx(lambda wb: [wb.active.append([1, 2, 3])])
    assert xlsx_tables.workbook_markdown(data) == ""


def test_workbook_markdown_error_in_sheet(monkeypatch):
    def boom(cells):
        raise RuntimeError("lỗi")

    monkeypatch.setattr(xlsx_tables, "find_regions", boom)
    data = _xlsx(lambda wb: [wb.active.append(["a", "b"])])
    assert xlsx_tables.workbook_markdown(data) == ""


# =====================================================================
# docx_charts
# =====================================================================


def test_tokenize_not_a_zip_or_no_document():
    assert docx_charts.tokenize_charts(b"rac") == (b"rac", [])
    no_doc = rewrite_zip(make_docx_with_chart(), "word/document.xml", lambda raw: None)
    assert docx_charts.tokenize_charts(no_doc) == (no_doc, [])


def test_tokenize_plain_docx_unchanged(docx_bytes):
    assert docx_charts.tokenize_charts(docx_bytes) == (docx_bytes, [])


def test_tokenize_unknown_rid_keeps_drawing():
    data = rewrite_zip(
        make_docx_with_chart(), "word/document.xml", lambda raw: raw.replace(b"rIdChart1", b"rIdNo")
    )
    assert docx_charts.tokenize_charts(data) == (data, [])


def test_tokenize_chart_error_gives_empty_and_token_removed(monkeypatch):
    def boom(*a):
        raise ValueError("chart hỏng")

    monkeypatch.setattr(xlsx_media, "chart_part_markdown", boom)
    tokenized, charts = docx_charts.tokenize_charts(make_docx_with_chart())
    assert charts == [""]
    assert b"QXCHART0000QX" in zipfile.ZipFile(io.BytesIO(tokenized)).read("word/document.xml")
    assert docx_charts.fill_tokens("A QXCHART0000QX B", charts) == "A  B"


def test_fill_tokens_duplicates_and_out_of_range():
    md = "đầu\n\nQXCHART0000QX\n\n\n\nQXCHART0000QX QXCHART0007QX cuối"
    assert docx_charts.fill_tokens(md, ["| bảng |"]) == "đầu\n\n| bảng |\n\n  cuối"
