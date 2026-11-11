"""Chạy các file mẫu trong samples/ qua ConvertActivities (Tesseract thật, không Vision).

uv run python samples/scripts/run_convert.py [tên-file ...]
"""

import asyncio
import sys
import time
import traceback
from pathlib import Path

from temporalio.testing import ActivityEnvironment

from ingest.convert.activities import ConvertActivities
from ingest.convert.ocr import TesseractOcrEngine
from ingest.core import keys
from ingest.core.models import FinalizeInput, IngestInput, OcrBatch
from ingest.core.storage import MemoryStorage

SAMPLES = Path(__file__).resolve().parents[1]
OUT = SAMPLES / "out"
OCR = TesseractOcrEngine()


async def convert(path: Path) -> str:
    st = MemoryStorage()
    doc_id = path.stem
    rk = keys.raw_key(doc_id, path.name)
    st.put(rk, path.read_bytes())
    acts = ConvertActivities(st, OCR, pages_per_batch=2, vision=None)
    inp = IngestInput(doc_id=doc_id, file_name=path.name, raw_key=rk)
    env = ActivityEnvironment()
    info = await env.run(acts.detect_format, inp)
    print(f"  kind={info.kind} page_count={info.page_count} ocr_batches={info.ocr_page_batches}")
    part = await env.run(acts.parse_document, inp)
    batches = []
    for i, pages in enumerate(info.ocr_page_batches):
        r = await env.run(acts.ocr_pages, OcrBatch(doc_id, pages, i, rk, info.kind))
        print(f"  batch {i} {pages}: confidence={r.confidence:.3f}")
        batches.append(r.batch_index)
    fin = FinalizeInput(doc_id, path.name, batches, part.page_count)
    res = await env.run(acts.finalize_markdown, fin)
    print(f"  chars={res.char_count}")
    return st.get(res.md_key).decode()


async def main(names: list[str]) -> int:
    OUT.mkdir(exist_ok=True)
    files = (
        [SAMPLES / n for n in names]
        if names
        else sorted(p for p in SAMPLES.iterdir() if p.suffix in {".docx", ".pdf", ".xlsx"})
    )
    failed = 0
    for path in files:
        print(f"== {path.name}")
        t = time.perf_counter()
        try:
            md = await convert(path)
        except Exception:
            failed += 1
            traceback.print_exc()
            continue
        out = OUT / f"{path.stem}.md"
        out.write_text(md, encoding="utf-8")
        print(f"  -> {out.relative_to(SAMPLES.parent)} ({time.perf_counter() - t:.1f}s)")
    return failed


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
