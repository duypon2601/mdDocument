"""Conversion Worker: convert-tq. Nặng CPU/GPU nên giới hạn số activity chạy đồng thời."""

import logging

from temporalio.client import Client
from temporalio.worker import Worker

from ingest.convert.activities import ConvertActivities
from ingest.convert.ocr import OcrEngine, RapidOcrEngine, TesseractOcrEngine
from ingest.convert.vision import OpenAICompatVision
from ingest.core.config import Settings, get_settings
from ingest.core.runtime import make_storage, run_main


def make_ocr(s: Settings | None = None) -> OcrEngine:
    """auto: Tesseract nếu máy có gói ngôn ngữ, không thì RapidOCR (mất dấu tiếng Việt)."""
    s = s or get_settings()
    tess = TesseractOcrEngine(s.ocr_lang)
    if s.ocr_engine == "tesseract" or (s.ocr_engine == "auto" and tess.available()):
        return tess
    if s.ocr_engine == "auto":
        logging.getLogger(__name__).warning(
            "Không thấy tesseract với gói %s; dùng RapidOCR, tiếng Việt sẽ mất dấu.", s.ocr_lang
        )
    return RapidOcrEngine()


def make_vision(s: Settings) -> OpenAICompatVision | None:
    if not s.vision_model:
        return None
    return OpenAICompatVision(s.vision_base_url, s.vision_api_key, s.vision_model, s.vision_timeout)


async def build(s: Settings, client: Client) -> Worker:
    a = ConvertActivities(
        make_storage(s),
        make_ocr(s),
        s.ocr_pages_per_batch,
        s.prefer_docling,
        vision=make_vision(s),
        docx_image_mode=s.docx_image_mode,
        docx_min_image_bytes=s.docx_min_image_bytes,
        min_ocr_confidence=s.min_ocr_confidence,
        xlsx_formulas=s.xlsx_formulas,
    )
    return Worker(
        client,
        task_queue=s.convert_tq,
        activities=[a.detect_format, a.parse_document, a.ocr_pages, a.finalize_markdown],
        max_concurrent_activities=s.convert_max_concurrent_activities,
    )


def main() -> None:
    run_main(build)


run = main


if __name__ == "__main__":
    main()
