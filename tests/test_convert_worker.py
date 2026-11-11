"""convert.worker: chọn OCR engine và Vision LLM từ settings."""

import logging

import pytest

from ingest.convert import worker
from ingest.convert.ocr import TesseractOcrEngine
from ingest.convert.vision import OpenAICompatVision
from ingest.core.config import Settings


def S(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


@pytest.mark.parametrize("tess_ok", [True, False])
def test_make_ocr(monkeypatch, caplog, tess_ok):
    monkeypatch.setattr(TesseractOcrEngine, "available", lambda self: tess_ok)
    with caplog.at_level(logging.WARNING):
        ocr = worker.make_ocr(S(ocr_lang="vie"))
    assert isinstance(ocr, TesseractOcrEngine) and ocr.lang == "vie"
    assert ("Vision LLM" in caplog.text) == (not tess_ok)


def test_make_ocr_default_settings(monkeypatch):
    monkeypatch.setattr(worker, "get_settings", lambda: S(ocr_lang="eng"))
    assert worker.make_ocr().lang == "eng"


def test_make_vision():
    assert worker.make_vision(S(vision_model="")) is None
    v = worker.make_vision(S(vision_model="qwen2-vl"))
    assert isinstance(v, OpenAICompatVision)
