"""convert.worker: chọn OCR engine và Vision LLM từ settings."""

import logging

import pytest

from ingest.convert import worker
from ingest.convert.ocr import RapidOcrEngine, TesseractOcrEngine
from ingest.convert.vision import OpenAICompatVision
from ingest.core.config import Settings


def S(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


@pytest.mark.parametrize(
    ("engine", "tess_ok", "expected"),
    [
        ("tesseract", False, TesseractOcrEngine),
        ("auto", True, TesseractOcrEngine),
        ("auto", False, RapidOcrEngine),
        ("rapidocr", True, RapidOcrEngine),
    ],
)
def test_make_ocr(monkeypatch, caplog, engine, tess_ok, expected):
    monkeypatch.setattr(TesseractOcrEngine, "available", lambda self: tess_ok)
    with caplog.at_level(logging.WARNING):
        ocr = worker.make_ocr(S(ocr_engine=engine, ocr_lang="vie"))
    assert isinstance(ocr, expected)
    if expected is TesseractOcrEngine:
        assert ocr.lang == "vie"
    warned = "mất dấu" in caplog.text
    assert warned == (engine == "auto" and not tess_ok)


def test_make_ocr_default_settings(monkeypatch):
    monkeypatch.setattr(worker, "get_settings", lambda: S(ocr_engine="rapidocr"))
    assert isinstance(worker.make_ocr(), RapidOcrEngine)


def test_make_vision():
    assert worker.make_vision(S(vision_model="")) is None
    v = worker.make_vision(S(vision_model="qwen2-vl"))
    assert isinstance(v, OpenAICompatVision)
