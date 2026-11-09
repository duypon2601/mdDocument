import json
from dataclasses import asdict

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from conftest import make_pdf
from ingest.convert.activities import ConvertActivities
from ingest.convert.ocr import FakeOcr
from ingest.convert.parsers.merge import drop_repeated_edges, merge_markdown, split_pages
from ingest.core import keys
from ingest.core.models import FinalizeInput, FormatInfo, IngestInput, OcrBatch
from ingest.core.storage import MemoryStorage

LONG = "This is a paragraph long enough to count as a text layer in the PDF."


def setup(name: str, data: bytes, ocr: FakeOcr | None = None):
    st = MemoryStorage()
    doc_id = "doc1"
    rk = keys.raw_key(doc_id, name)
    st.put(rk, data)
    acts = ConvertActivities(st, ocr or FakeOcr(), pages_per_batch=2)
    return st, acts, IngestInput(doc_id=doc_id, file_name=name, raw_key=rk)


async def test_detect_pdf_mixed_pages():
    st, acts, inp = setup("a.pdf", make_pdf([LONG, None, None, None, LONG]))
    info = await ActivityEnvironment().run(acts.detect_format, inp)
    assert info.kind == "pdf" and info.page_count == 5 and info.has_text
    assert info.ocr_page_batches == [[1, 2], [3]]
    assert FormatInfo(**json.loads(json.dumps(asdict(info)))) == info


async def test_detect_docx_html_text_image(docx_bytes):
    env = ActivityEnvironment()
    for name, data, kind in [
        ("a.docx", docx_bytes, "docx"),
        ("a.html", b"<html><body><h1>x</h1></body></html>", "html"),
        ("a.txt", b"hello", "text"),
        ("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20, "image"),
    ]:
        _, acts, inp = setup(name, data)
        info = await env.run(acts.detect_format, inp)
        assert info.kind == kind
        if kind == "image":
            assert info.ocr_page_batches == [[0]]


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("a.xyz", b"\x00\x01\x02binary", "UNSUPPORTED_FORMAT"),
        ("a.pdf", b"%PDF-1.7 garbage not a pdf", "FILE_CORRUPTED"),
        ("a.docx", b"PK\x03\x04broken", "FILE_CORRUPTED"),
        ("a.pdf", b"", "FILE_CORRUPTED"),
        ("a.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 50, "PASSWORD_PROTECTED"),
    ],
)
async def test_detect_errors_non_retryable(name, data, code):
    _, acts, inp = setup(name, data)
    with pytest.raises(ApplicationError) as ei:
        await ActivityEnvironment().run(acts.detect_format, inp)
    assert ei.value.type == code and ei.value.non_retryable


async def test_encrypted_pdf_password_protected():
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), LONG)
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    _, acts, inp = setup("a.pdf", data)
    with pytest.raises(ApplicationError) as ei:
        await ActivityEnvironment().run(acts.parse_document, inp)
    assert ei.value.type == "PASSWORD_PROTECTED" and ei.value.non_retryable


async def test_parse_pdf_only_text_pages_and_rerun():
    st, acts, inp = setup("a.pdf", make_pdf([LONG, None]))
    env = ActivityEnvironment()
    r1 = await env.run(acts.parse_document, inp)
    first = st.get(r1.md_key)
    r2 = await env.run(acts.parse_document, inp)
    assert r1 == r2 and st.get(r2.md_key) == first
    md = first.decode()
    assert "<!-- page: 1 -->" in md and "<!-- page: 2 -->" not in md
    assert "long enough" in md and r1.page_count == 2


async def test_parse_docx_html(docx_bytes):
    env = ActivityEnvironment()
    st, acts, inp = setup("a.docx", docx_bytes)
    r = await env.run(acts.parse_document, inp)
    md = st.get(r.md_key).decode()
    assert "Hợp đồng mẫu" in md and "Thanh toán" in md
    html = "<html><body><script>x()</script><h1>Tiêu đề</h1><p>Nội dung</p></body></html>"
    st, acts, inp = setup("a.html", html.encode())
    r = await env.run(acts.parse_document, inp)
    md = st.get(r.md_key).decode()
    assert "# Tiêu đề" in md and "x()" not in md


async def test_ocr_pages_confidence_and_output():
    ocr = FakeOcr(text="chữ trong ảnh", confidence=0.4)
    st, acts, inp = setup("a.pdf", make_pdf([LONG, None, None]), ocr)
    res = await ActivityEnvironment().run(
        acts.ocr_pages, OcrBatch(inp.doc_id, [1, 2], 0, inp.raw_key, "pdf")
    )
    assert res.confidence == pytest.approx(0.4) and ocr.calls == 2
    md = st.get(res.md_key).decode()
    assert md.index("page: 2") < md.index("page: 3") and "chữ trong ảnh" in md
    assert res.md_key == keys.md_raw_ocr_key("doc1", 0)


async def test_ocr_image_file():
    ocr = FakeOcr(text="scan", confidence=0.9)
    st, acts, inp = setup("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20, ocr)
    res = await ActivityEnvironment().run(
        acts.ocr_pages, OcrBatch(inp.doc_id, [0], 0, inp.raw_key, "image")
    )
    assert "scan" in st.get(res.md_key).decode()


async def test_finalize_merges_by_page_order_and_frontmatter():
    st, acts, inp = setup("a.pdf", make_pdf([LONG]))
    text = "<!-- page: 1 -->\n\nTrang một\n\n<!-- page: 3 -->\n\nTrang ba"
    st.put(keys.md_raw_text_key("doc1"), text.encode())
    st.put(keys.md_raw_ocr_key("doc1", 0), b"<!-- page: 2 -->\n\nTrang hai")
    res = await ActivityEnvironment().run(
        acts.finalize_markdown, FinalizeInput("doc1", "a.pdf", [0], 3)
    )
    md = st.get(res.md_key).decode()
    assert md.startswith("---") and "title: a.pdf" in md
    assert md.index("Trang một") < md.index("Trang hai") < md.index("Trang ba")
    assert res.md_key == "md/doc1.md"


async def test_finalize_empty_document():
    st, acts, _ = setup("a.pdf", make_pdf([LONG]))
    st.put(keys.md_raw_text_key("doc1"), b"")
    with pytest.raises(ApplicationError) as ei:
        await ActivityEnvironment().run(acts.finalize_markdown, FinalizeInput("doc1", "a.pdf"))
    assert ei.value.type == "EMPTY_DOCUMENT" and ei.value.non_retryable


def test_drop_repeated_header_footer():
    pages = {
        i: f"CÔNG TY ABC\n\nNội dung riêng trang {i} " + "x" * i + f"\n\nTrang {i}"
        for i in range(1, 6)
    }
    out = drop_repeated_edges(pages)
    assert all("CÔNG TY ABC" not in t for t in out.values())
    assert all("Nội dung riêng" in t for t in out.values())
    assert all(f"Trang {i}\n" not in out[i] + "\n" for i in out)


def test_merge_and_split_roundtrip():
    md, n = merge_markdown(["<!-- page: 2 -->\n\nB", "<!-- page: 1 -->\n\nA"], "f.pdf", "d", 2)
    assert n == 2
    body = md.split("---", 2)[2]
    assert list(split_pages(body)) == [1, 2]
