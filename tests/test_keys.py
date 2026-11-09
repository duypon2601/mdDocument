import json
import uuid
from dataclasses import asdict

from ingest.core import keys
from ingest.core.models import FormatInfo, IngestInput


def test_keys_layout():
    assert keys.raw_key("d1", "a.pdf") == "raw/d1/a.pdf"
    assert keys.md_raw_text_key("d1") == "md-raw/d1/text.md"
    assert keys.md_raw_ocr_key("d1", 3) == "md-raw/d1/ocr/3.md"
    assert keys.md_key("d1") == "md/d1.md"
    assert keys.chunk_batch_key("d1", 2, 5) == "chunks/d1/v2/batch-5.jsonl"


def test_point_id_deterministic_and_distinct():
    a = keys.point_id("d1", 1, 0)
    assert a == keys.point_id("d1", 1, 0)
    assert uuid.UUID(a).version == 5
    others = {keys.point_id("d1", 2, 0), keys.point_id("d1", 1, 1), keys.point_id("d2", 1, 0)}
    assert a not in others and len(others) == 3


def test_payload_json_roundtrip():
    f = FormatInfo(doc_id="d", kind="pdf", ocr_page_batches=[[0, 1], [2]])
    assert FormatInfo(**json.loads(json.dumps(asdict(f)))) == f
    assert IngestInput(doc_id="d", file_name="f", raw_key="k").index_version == 1
