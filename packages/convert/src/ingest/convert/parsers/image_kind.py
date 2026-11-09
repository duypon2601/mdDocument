"""Phân biệt ảnh tài liệu (scan, chụp văn bản) với chart, sơ đồ, ảnh bảng.

Ảnh tài liệu đi OCR. Chart, sơ đồ và bảng chụp đi Vision LLM, vì OCR chỉ ra chữ vụn
và mất quan hệ nhãn - giá trị. Ngưỡng đo trên samples/ (xem samples/scripts):

    loại ảnh        màu     độ dài dòng   tỷ lệ chữ số
    scan văn bản    0%      47-55         4-11%
    chữ ký          0%      38            0%
    ảnh bảng        0%      47            46%
    chart           8-38%   9-15          7-28%
"""

from dataclasses import dataclass

COLOR_DELTA = 60  # chênh lệch kênh màu lớn hơn mức này là điểm ảnh "có màu"
SAMPLE_PIXELS = 40_000

MIN_TEXT_CHARS = 40  # ít chữ hơn: logo, ảnh chụp, sơ đồ thưa chữ
SHORT_LINE = 20  # dòng trung bình ngắn hơn: nhãn trục, chú thích, ô sơ đồ
COLOR_RATIO = 0.03  # có màu và dòng ngắn: chart
DIGIT_RATIO = 0.25  # phần lớn là số: bảng hoặc chart


@dataclass
class TextStats:
    chars: int
    lines: int
    avg_line: float
    digit_ratio: float


def text_stats(text: str) -> TextStats:
    chars = [c for c in text if not c.isspace()]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    avg = sum(len(ln) for ln in lines) / len(lines) if lines else 0.0
    digits = sum(c.isdigit() for c in chars) / len(chars) if chars else 0.0
    return TextStats(len(chars), len(lines), avg, digits)


def color_ratio(png: bytes) -> float:
    """Tỷ lệ điểm ảnh có màu (lấy mẫu đều). Ảnh không đọc được trả 0."""
    try:
        import pymupdf

        pix = pymupdf.Pixmap(png)
        if pix.n - pix.alpha < 3:  # ảnh xám
            return 0.0
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.colorspace is not None and pix.colorspace.n != 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    except Exception:
        return 0.0
    total = pix.width * pix.height
    if total == 0:
        return 0.0
    step = max(1, total // SAMPLE_PIXELS)
    data, n = pix.samples, pix.n
    colored = sampled = 0
    for i in range(0, total, step):
        r, g, b = data[i * n], data[i * n + 1], data[i * n + 2]
        sampled += 1
        if max(r, g, b) - min(r, g, b) > COLOR_DELTA:
            colored += 1
    return colored / sampled


def graphic_reason(text: str, png: bytes | None = None) -> str | None:
    """Lý do nên đọc ảnh bằng Vision LLM thay vì giữ kết quả OCR; None nếu là ảnh tài liệu."""
    st = text_stats(text)
    if st.chars < MIN_TEXT_CHARS:
        return "ít chữ"
    if st.digit_ratio > DIGIT_RATIO:
        return f"nhiều số {st.digit_ratio:.0%}"
    if st.lines >= 3 and st.avg_line < SHORT_LINE:
        return "dòng ngắn"
    # con dấu đỏ, ảnh chụp văn bản có nền màu vẫn có dòng dài nên không bị tính là chart
    if png is not None and st.avg_line < 25 and color_ratio(png) > COLOR_RATIO:
        return "có màu, dòng ngắn"
    return None


def is_graphic(text: str, png: bytes | None = None) -> bool:
    return graphic_reason(text, png) is not None
