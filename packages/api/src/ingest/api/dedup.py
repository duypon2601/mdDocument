"""doc_id sinh từ SHA-256 nội dung: file trùng cho cùng doc_id nên không tạo job mới."""

import hashlib


def compute_doc_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
