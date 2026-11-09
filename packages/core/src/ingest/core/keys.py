"""Key trên storage và point id, sinh hoàn toàn từ input để chạy lại ghi đè cùng nội dung."""

import uuid

# Namespace cố định cho uuid5 (không đổi, đổi là mất idempotent)
POINT_NAMESPACE = uuid.UUID("6f1c2f0e-4c3a-5b7e-9a1d-0d6b1f3a9c11")


def raw_key(doc_id: str, file_name: str) -> str:
    return f"raw/{doc_id}/{file_name}"


def md_raw_text_key(doc_id: str) -> str:
    return f"md-raw/{doc_id}/text.md"


def md_raw_ocr_key(doc_id: str, batch: int) -> str:
    return f"md-raw/{doc_id}/ocr/{batch}.md"


def md_key(doc_id: str) -> str:
    return f"md/{doc_id}.md"


def chunk_batch_key(doc_id: str, index_version: int, batch: int) -> str:
    return f"chunks/{doc_id}/v{index_version}/batch-{batch}.jsonl"


def point_id(doc_id: str, index_version: int, chunk_index: int) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, f"{doc_id}:{index_version}:{chunk_index}"))
