"""Bổ sung cho convert: batching OCR, mã lỗi non-retryable, idempotent, finalize."""

import io
import zipfile

import pymupdf
import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from conftest import make_pdf
from ingest.convert.activities import ConvertActivities, chunked
from ingest.convert.ocr import FakeOcr
from ingest.convert.parsers.merge import drop_repeated_edges, merge_markdown, split_pages
from ingest.core import keys
from ingest.core.models import FinalizeInput, IngestInput, OcrBatch
from ingest.core.storage import MemoryStorage

WORDS = ["một", "hai", "ba", "bốn", "năm", "sáu"]
LONG = "This is a paragraph long enough to count as a text layer in the PDF."
ENV = ActivityEnvironment


def setup(name, data, ocr=None, per_batch=10):
    st = MemoryStorage()
    rk = keys.raw_key("doc1", name)
    st.put(rk, data)
    return (
        st,
        ConvertActivities(st, ocr or FakeOcr(), pages_per_batch=per_batch),
        IngestInput(doc_id="doc1", file_name=name, raw_key=rk),
    )


async def err_of(fn, arg):
    with pytest.raises(ApplicationError) as ei:
        await ENV().run(fn, arg)
    return ei.value


# ---------- OCR page detection / batching ----------


@pytest.mark.parametrize(
    ("n_scanned", "expected_sizes"),
    [(1, [1]), (9, [9]), (10, [10]), (11, [10, 1]), (25, [10, 10, 5])],
)
async def test_default_batch_is_ten_pages(n_scanned, expected_sizes):
    st, acts, inp = setup("a.pdf", make_pdf([None] * n_scanned))  # mặc định 10 trang/lô
    info = await ENV().run(acts.detect_format, inp)
    assert [len(b) for b in info.ocr_page_batches] == expected_sizes
    assert [p for b in info.ocr_page_batches for p in b] == list(range(n_scanned))
    assert info.has_text is False


async def test_text_only_pdf_needs_no_ocr():
    _, acts, inp = setup("a.pdf", make_pdf([LONG, LONG]))
    info = await ENV().run(acts.detect_format, inp)
    assert info.ocr_page_batches == [] and info.has_text and info.page_count == 2


async def test_page_with_almost_no_text_goes_to_ocr():
    _, acts, inp = setup("a.pdf", make_pdf([LONG, "Hi", LONG]))
    info = await ENV().run(acts.detect_format, inp)
    assert info.ocr_page_batches == [[1]]


async def test_detect_format_is_idempotent():
    _, acts, inp = setup("a.pdf", make_pdf([LONG, None, None]), per_batch=1)
    a = await ENV().run(acts.detect_format, inp)
    b = await ENV().run(acts.detect_format, inp)
    assert a == b and a.ocr_page_batches == [[1], [2]]


def test_chunked_edge_cases():
    assert chunked([], 10) == []
    assert chunked([1, 2, 3], 10) == [[1, 2, 3]]
    assert chunked(list(range(20)), 10) == [list(range(10)), list(range(10, 20))]


# ---------- non-retryable error codes ----------


async def test_detect_empty_zero_page_and_password_codes():
    # PDF hợp lệ về header nhưng pymupdf không mở được
    _, acts, inp = setup("a.pdf", b"%PDF-1.4\n%%EOF")
    e = await err_of(acts.detect_format, inp)
    assert e.type == "FILE_CORRUPTED" and e.non_retryable


async def test_detect_encrypted_pdf_is_password_protected():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), LONG)
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    _, acts, inp = setup("a.pdf", data)
    e = await err_of(acts.detect_format, inp)
    assert e.type == "PASSWORD_PROTECTED" and e.non_retryable


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("a.pdf", b"%PDF-1.7 garbage", "FILE_CORRUPTED"),
        ("a.xyz", b"\x00\x01\x02binary", "UNSUPPORTED_FORMAT"),
        ("a.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 50, "UNSUPPORTED_FORMAT"),
        ("a.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 50, "PASSWORD_PROTECTED"),
        ("a.pptx", b"", "FILE_CORRUPTED"),
    ],
)
async def test_parse_document_error_codes_non_retryable(name, data, code):
    _, acts, inp = setup(name, data)
    e = await err_of(acts.parse_document, inp)
    assert e.type == code and e.non_retryable


async def test_parse_zip_that_is_not_office_is_unsupported():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "x")
    _, acts, inp = setup("a.zip", buf.getvalue())
    e = await err_of(acts.parse_document, inp)
    assert e.type == "UNSUPPORTED_FORMAT" and e.non_retryable


async def test_parse_docx_with_corrupt_body_is_file_corrupted():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<<<not xml")
    _, acts, inp = setup("a.docx", buf.getvalue())
    e = await err_of(acts.parse_document, inp)
    assert e.type == "FILE_CORRUPTED" and e.non_retryable


@pytest.mark.parametrize("fn_name", ["detect_format", "parse_document"])
async def test_missing_raw_file_is_retryable_not_business_error(fn_name):
    st, acts, inp = setup("a.pdf", make_pdf([LONG]))
    st.delete(inp.raw_key)
    with pytest.raises(FileNotFoundError):  # lỗi hạ tầng: để Temporal retry
        await ENV().run(getattr(acts, fn_name), inp)


async def test_ocr_pages_corrupt_pdf_is_file_corrupted():
    _, acts, inp = setup("a.pdf", b"%PDF-1.7 garbage")
    e = await err_of(acts.ocr_pages, OcrBatch("doc1", [0], 0, inp.raw_key, "pdf"))
    assert e.type == "FILE_CORRUPTED" and e.non_retryable


async def test_finalize_whitespace_and_marker_only_is_empty_document():
    st, acts, _ = setup("a.pdf", make_pdf([LONG]))
    st.put(keys.md_raw_text_key("doc1"), b"<!-- page: 1 -->\n\n  \n")
    st.put(keys.md_raw_ocr_key("doc1", 0), b"<!-- page: 2 -->\n\n")
    e = await err_of(acts.finalize_markdown, FinalizeInput("doc1", "a.pdf", [0], 2))
    assert e.type == "EMPTY_DOCUMENT" and e.non_retryable
    assert not st.exists(keys.md_key("doc1"))  # không ghi markdown rác


async def test_finalize_without_any_part_is_empty_document():
    _, acts, _ = setup("a.pdf", make_pdf([LONG]))
    e = await err_of(acts.finalize_markdown, FinalizeInput("doc1", "a.pdf"))
    assert e.type == "EMPTY_DOCUMENT"


# ---------- parse / OCR behaviour and idempotency ----------


async def test_parse_image_writes_empty_text_part():
    st, acts, inp = setup("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    r = await ENV().run(acts.parse_document, inp)
    assert st.get(r.md_key) == b"" and r.page_count == 0


async def test_parse_pdf_text_pages_keep_original_page_numbers():
    st, acts, inp = setup("a.pdf", make_pdf([None, LONG, None, LONG]))
    r = await ENV().run(acts.parse_document, inp)
    md = st.get(r.md_key).decode()
    assert "<!-- page: 2 -->" in md and "<!-- page: 4 -->" in md
    assert "<!-- page: 1 -->" not in md and "<!-- page: 3 -->" not in md
    assert r.md_key == keys.md_raw_text_key("doc1")


async def test_ocr_pages_rerun_overwrites_same_key_same_content():
    ocr = FakeOcr(text="  chữ  ", confidence=0.8)
    st, acts, inp = setup("a.pdf", make_pdf([None, None]), ocr)
    batch = OcrBatch("doc1", [0, 1], 3, inp.raw_key, "pdf")
    r1 = await ENV().run(acts.ocr_pages, batch)
    c1 = st.get(r1.md_key)
    r2 = await ENV().run(acts.ocr_pages, batch)
    assert r1 == r2 and st.get(r2.md_key) == c1
    assert r1.md_key == keys.md_raw_ocr_key("doc1", 3)
    assert c1.decode().count("chữ") == 2 and "  chữ  " not in c1.decode()
    assert st.list_keys("md-raw/doc1/ocr/") == [r1.md_key]


async def test_ocr_confidence_is_mean_over_pages():
    class Seq:
        def __init__(self):
            self.vals = iter([0.2, 0.6])

        def recognize(self, png):
            return "t", next(self.vals)

    _, acts, inp = setup("a.pdf", make_pdf([None, None]), Seq())
    res = await ENV().run(acts.ocr_pages, OcrBatch("doc1", [0, 1], 0, inp.raw_key, "pdf"))
    assert res.confidence == pytest.approx(0.4)


async def test_ocr_pages_empty_batch_defaults_to_full_confidence():
    st, acts, inp = setup("a.pdf", make_pdf([None]))
    res = await ENV().run(acts.ocr_pages, OcrBatch("doc1", [], 0, inp.raw_key, "pdf"))
    assert res.confidence == 1.0 and st.get(res.md_key) == b""


# ---------- finalize_markdown: ordering + header/footer ----------


async def run_finalize(st, acts, ocr_batches, name="a.pdf", pages=0):
    return await ENV().run(acts.finalize_markdown, FinalizeInput("doc1", name, ocr_batches, pages))


def body_of(st) -> str:
    return st.get(keys.md_key("doc1")).decode().split("---", 2)[2]


async def test_finalize_orders_pages_numerically_not_lexically():
    st, acts, _ = setup("a.pdf", make_pdf([LONG]))
    st.put(
        keys.md_raw_text_key("doc1"),
        b"<!-- page: 10 -->\n\nMuoi\n\n<!-- page: 1 -->\n\nMot\n\n<!-- page: 2 -->\n\nHai",
    )
    await run_finalize(st, acts, [])
    b = body_of(st)
    assert b.index("Mot") < b.index("Hai") < b.index("Muoi")


async def test_finalize_ocr_batches_out_of_order_and_missing_batch():
    st, acts, _ = setup("a.pdf", make_pdf([LONG]))
    st.put(keys.md_raw_ocr_key("doc1", 0), b"<!-- page: 1 -->\n\nA")
    st.put(keys.md_raw_ocr_key("doc1", 1), b"<!-- page: 2 -->\n\nB")
    # batch 2 không tồn tại: bị bỏ qua chứ không lỗi
    await run_finalize(st, acts, [2, 1, 0])
    b = body_of(st)
    assert b.index("A") < b.index("B")


async def test_finalize_is_idempotent():
    st, acts, _ = setup("a.pdf", make_pdf([LONG]))
    st.put(keys.md_raw_text_key("doc1"), b"<!-- page: 1 -->\n\nXin chao")
    r1 = await run_finalize(st, acts, [], pages=1)
    first = st.get(r1.md_key)
    r2 = await run_finalize(st, acts, [], pages=1)
    assert r1 == r2 and st.get(r2.md_key) == first


async def test_finalize_office_text_without_markers_comes_first_without_marker():
    st, acts, _ = setup("a.docx", b"x")
    st.put(keys.md_raw_text_key("doc1"), "# Hợp đồng\n\nNội dung".encode())
    r = await run_finalize(st, acts, [], name="a.docx")
    md = st.get(r.md_key).decode()
    assert "page:" not in md and "# Hợp đồng" in md and "title: a.docx" in md


async def test_finalize_strips_repeating_header_footer_through_activity():
    st, acts, _ = setup("a.pdf", make_pdf([LONG]))
    pages = "\n\n".join(
        f"<!-- page: {i} -->\n\nCÔNG TY ABC\n\nNội dung {w}\n\nTrang {i}/6"
        for i, w in enumerate(WORDS, 1)
    )
    st.put(keys.md_raw_text_key("doc1"), pages.encode())
    await run_finalize(st, acts, [], pages=6)
    b = body_of(st)
    assert "CÔNG TY ABC" not in b and "/6" not in b
    assert all(f"Nội dung {w}" in b for w in WORDS)


def test_frontmatter_page_count_falls_back_to_counted_pages():
    md, _ = merge_markdown(["<!-- page: 1 -->\n\nA\n\n<!-- page: 2 -->\n\nB"], "f.pdf", "d", 0)
    assert "pages: 2" in md and "doc_id: d" in md


def test_split_pages_edge_cases():
    assert split_pages("") == {}
    assert split_pages("<!-- page: 1 -->\n\n   ") == {}
    assert split_pages("<!--page:3-->x") == {3: "x"}  # marker lỏng khoảng trắng
    assert split_pages("pre\n\n<!-- page: 1 -->\n\nA") == {0: "pre", 1: "A"}


def mkpages(n, header="CÔNG TY ABC", footer="Trang {i}"):
    bodies = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
    return {i: f"{header}\n\nThân {bodies[i - 1]}\n\n{footer.format(i=i)}" for i in range(1, n + 1)}


def test_header_footer_not_removed_below_three_pages():
    pages = mkpages(2)
    assert drop_repeated_edges(pages) == pages


def test_header_removed_on_exactly_three_pages_with_varying_numbers():
    out = drop_repeated_edges(mkpages(3))
    assert all("CÔNG TY ABC" not in t and "Trang" not in t for t in out.values())
    assert all("Thân" in t for t in out.values())


def test_line_repeated_in_few_pages_is_kept():
    pages = {i: f"Thân {i}\n\nGhi chú" if i == 1 else f"Thân {i}\n\nkhác {i}" for i in range(1, 7)}
    out = drop_repeated_edges(pages)
    assert "Ghi chú" in out[1]


def test_repeated_line_in_page_middle_is_kept():
    pages = {}
    for i in range(1, 6):
        mid = "\n\n".join(f"đoạn {i}.{k}" for k in range(12))
        pages[i] = f"CÔNG TY ABC\n\n{mid}\n\nChân {i}"
    # thêm cùng dòng ở giữa trang 1
    lines = pages[1].split("\n\n")
    lines.insert(6, "CÔNG TY ABC")
    pages[1] = "\n\n".join(lines)
    out = drop_repeated_edges(pages)
    assert "CÔNG TY ABC" in out[1]  # chỉ bỏ ở rìa, không bỏ giữa trang


def test_long_repeated_lines_are_content_not_headers():
    long_line = "x" * 150
    pages = {i: f"{long_line}\n\nThân {i}\n\nCuối {i}" for i in range(1, 7)}
    assert all(long_line in t for t in drop_repeated_edges(pages).values())


def test_page_zero_is_never_stripped():
    pages = {0: "CÔNG TY ABC\n\nVăn bản", **mkpages(5)}
    assert "CÔNG TY ABC" in drop_repeated_edges(pages)[0]


def test_merge_markdown_empty_inputs():
    assert merge_markdown([], "f", "d") == ("", 0)
    assert merge_markdown(["", "  "], "f", "d") == ("", 0)
