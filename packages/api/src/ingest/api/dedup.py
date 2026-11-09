"""doc_id sinh từ SHA-256 nội dung: file trùng cho cùng doc_id nên không tạo job mới."""

import hashlib

LEGACY_PREFIX = "legacy-"


V1_PREFIX = "v1-"


def compute_doc_id(data: bytes, extract_media: bool = True, pipeline_version: int = 2) -> str:
    """Bản cũ (không bóc ảnh) có id riêng để cùng một file chạy được cả hai chế độ.

    Cột doc_id dài 64 ký tự nên cắt bớt hash cho vừa tiền tố (vẫn còn 228 bit).
    """
    digest = hashlib.sha256(data).hexdigest()
    if extract_media and pipeline_version == 1:
        return V1_PREFIX + digest[: 64 - len(V1_PREFIX)]
    if extract_media:
        return digest
    return LEGACY_PREFIX + digest[: 64 - len(LEGACY_PREFIX)]


def is_legacy(doc_id: str) -> bool:
    return doc_id.startswith(LEGACY_PREFIX)


def profile_of(doc_id: str) -> str:
    """legacy | v1 | v2, suy ra từ tiền tố doc_id nên không cần thêm cột DB."""
    if doc_id.startswith(LEGACY_PREFIX):
        return "legacy"
    return "v1" if doc_id.startswith(V1_PREFIX) else "v2"
