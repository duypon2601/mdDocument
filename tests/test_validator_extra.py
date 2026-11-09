"""Edge case của validator upload (không cần Temporal)."""

import io
import zipfile

import pytest

from conftest import make_pdf
from ingest.api.validator import (
    DOCX,
    HTML,
    MARKDOWN,
    PDF,
    TEXT,
    ValidationError,
    detect_mime,
    safe_name,
    validate_upload,
)  # fmt: skip

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def zip_with(*names: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return buf.getvalue()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\a\\báo cáo.pdf", "báo cáo.pdf"),
        ("/abs/path/x.pdf", "x.pdf"),
        ("", "unnamed"),
        (None, "unnamed"),
        ("   ", "unnamed"),
        ("dir/", "dir"),
        (".", "unnamed"),
        ("hợp đồng 2026.pdf", "hợp đồng 2026.pdf"),
    ],
)
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_safe_name_never_returns_dot_dot():
    assert safe_name("..") not in ("..", ".")
    assert safe_name("a/..") not in ("..", ".")


def test_size_boundary_exact_max_ok_one_over_rejected():
    data = make_pdf(["x"])
    assert validate_upload("a.pdf", data, len(data)).size == len(data)
    with pytest.raises(ValidationError) as ei:
        validate_upload("a.pdf", data, len(data) - 1)
    assert ei.value.code == "FILE_TOO_LARGE" and ei.value.status_code == 413


def test_empty_file_is_400():
    with pytest.raises(ValidationError) as ei:
        validate_upload("a.pdf", b"", 100)
    assert ei.value.code == "EMPTY_FILE" and ei.value.status_code == 400


def test_empty_checked_before_size_even_with_zero_max():
    with pytest.raises(ValidationError) as ei:
        validate_upload("a.pdf", b"", 0)
    assert ei.value.code == "EMPTY_FILE"


def test_validated_name_is_sanitized():
    v = validate_upload("../../x/a.pdf", make_pdf(["x"]), 10**6)
    assert v.file_name == "a.pdf" and v.mime == PDF


def test_content_beats_extension_pdf_named_txt():
    assert detect_mime("a.txt", make_pdf(["x"])) == PDF


def test_png_named_pdf_is_image_not_pdf():
    assert detect_mime("a.pdf", PNG) == "image/png"


def test_text_named_pdf_is_not_trusted_as_pdf():
    assert detect_mime("a.pdf", "chỉ là chữ thường".encode()) != PDF


@pytest.mark.parametrize(
    ("name", "data", "mime"),
    [
        ("a.md", "# Tiêu đề\n\nNội dung".encode(), MARKDOWN),
        ("a.txt", "Xin chào Việt Nam".encode(), TEXT),
        ("a.html", b"<!DOCTYPE html><html><body>x</body></html>", HTML),
        ("a", b"<html><body>x</body></html>", HTML),
    ],
)
def test_textual_formats(name, data, mime):
    assert validate_upload(name, data, 10**6).mime == mime


def test_office_detected_from_zip_members_regardless_of_extension():
    for members, mime_suffix in [
        (("word/document.xml",), "wordprocessingml"),
        (("ppt/presentation.xml",), "presentationml"),
        (("xl/workbook.xml",), "spreadsheetml"),
    ]:
        assert mime_suffix in validate_upload("noext.bin", zip_with(*members), 10**6).mime


def test_plain_zip_with_zip_extension_rejected():
    with pytest.raises(ValidationError) as ei:
        validate_upload("a.zip", zip_with("a.txt"), 10**6)
    assert ei.value.code == "UNSUPPORTED_FORMAT" and ei.value.status_code == 415


@pytest.mark.parametrize(
    "data",
    [b"\x00\x01\x02\x03binary", b"MZ\x90\x00\x03\x00\x00\x00", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
)
def test_binary_blobs_rejected_even_with_friendly_extension(data):
    for name in ("a.txt", "a.docx", "a.pdf"):
        with pytest.raises(ValidationError) as ei:
            validate_upload(name, data, 10**6)
        assert ei.value.code == "UNSUPPORTED_FORMAT"


def test_binary_with_null_bytes_named_txt_rejected():
    with pytest.raises(ValidationError):
        validate_upload("a.txt", b"abc\x00def" * 10, 10**6)


def test_real_docx_accepted(docx_bytes):
    assert validate_upload("a.docx", docx_bytes, 10**6).mime == DOCX
