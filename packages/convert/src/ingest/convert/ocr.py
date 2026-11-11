"""OCR engine: Tesseract với gói `vie` (đọc đúng dấu tiếng Việt), FakeOcr cho test."""

import shutil
import subprocess
from functools import lru_cache
from typing import Protocol

from temporalio.exceptions import ApplicationError


class OcrEngine(Protocol):
    def recognize(self, png: bytes) -> tuple[str, float]:
        """Trả (text, độ tin cậy trung bình 0..1)."""
        ...


class FakeOcr:
    def __init__(self, text: str = "Văn bản OCR giả lập", confidence: float = 0.95) -> None:
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def recognize(self, png: bytes) -> tuple[str, float]:
        self.calls += 1
        return self.text, self.confidence


@lru_cache
def tesseract_langs(binary: str = "tesseract") -> frozenset[str]:
    """Ngôn ngữ Tesseract đã cài. Không có Tesseract trả tập rỗng."""
    path = shutil.which(binary)
    if not path:
        return frozenset()
    try:
        out = subprocess.run(
            [path, "--list-langs"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    lines = out.stdout.splitlines()[1:]  # dòng đầu là "List of available languages..."
    return frozenset(ln.strip() for ln in lines if ln.strip())


class TesseractOcrEngine:
    """Gọi CLI tesseract (cần gói ngôn ngữ, ví dụ apt install tesseract-ocr-vie)."""

    def __init__(self, lang: str = "vie+eng", binary: str = "tesseract", timeout: float = 120):
        self.lang = lang
        self.binary = binary
        self.timeout = timeout

    def available(self) -> bool:
        return all(code in tesseract_langs(self.binary) for code in self.lang.split("+"))

    def recognize(self, png: bytes) -> tuple[str, float]:
        path = shutil.which(self.binary)
        if not path or not self.available():
            raise ApplicationError(
                f"Chưa cài tesseract hoặc gói ngôn ngữ {self.lang}",
                type="OCR_UNAVAILABLE",
                non_retryable=True,
            )
        out = subprocess.run(
            [path, "stdin", "stdout", "-l", self.lang, "--psm", "3", "tsv"],
            input=png,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if out.returncode != 0:
            # ảnh hỏng hoặc định dạng lạ: lỗi xác định, chạy lại cũng vậy
            raise ApplicationError(
                f"tesseract lỗi: {out.stderr.decode(errors='replace')[:300]}",
                type="OCR_FAILED",
                non_retryable=True,
            )
        return parse_tsv(out.stdout.decode("utf-8", errors="replace"))


def parse_tsv(tsv: str) -> tuple[str, float]:
    """TSV của tesseract thành (text giữ dòng và đoạn, độ tin cậy trung bình 0..1)."""
    paragraphs: dict[tuple[str, str, str], dict[str, list[str]]] = {}
    confs: list[float] = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":  # level 5 = từ
            continue
        word = cols[11].strip()
        if not word:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        if conf >= 0:
            confs.append(conf / 100)
        key = (cols[1], cols[2], cols[3])  # trang, block, đoạn
        paragraphs.setdefault(key, {}).setdefault(cols[4], []).append(word)
    text = "\n\n".join(
        "\n".join(" ".join(words) for words in lines.values()) for lines in paragraphs.values()
    )
    if not text:
        return "", 1.0
    return text, sum(confs) / len(confs) if confs else 0.0
