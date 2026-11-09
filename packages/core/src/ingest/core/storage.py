# S3Storage adapted from rag-starter (MIT, Copyright (c) 2026 Anas Ahmad)
"""Object storage: S3/MinIO thật hoặc bộ nhớ (test)."""

import io
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list_keys(self, prefix: str) -> list[str]: ...
    def delete(self, key: str) -> None: ...


class MemoryStorage:
    def __init__(self) -> None:
        self._d: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._d[key] = bytes(data)

    def get(self, key: str) -> bytes:
        try:
            return self._d[key]
        except KeyError:
            raise FileNotFoundError(key) from None

    def exists(self, key: str) -> bool:
        return key in self._d

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._d if k.startswith(prefix))

    def delete(self, key: str) -> None:
        self._d.pop(key, None)


class S3Storage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        import boto3
        from botocore.client import Config

        self.bucket = bucket
        self._c = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region,
            # MinIO cần path-style
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        """Tạo bucket nếu chưa có. Idempotent."""
        from botocore.exceptions import ClientError

        try:
            self._c.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "403"):
                raise
            self._c.create_bucket(Bucket=self.bucket)
            logger.info("Đã tạo bucket '%s'.", self.bucket)

    def put(self, key: str, data: bytes) -> None:
        self._c.upload_fileobj(io.BytesIO(data), self.bucket, key)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self._c.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(key) from e
            raise

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._c.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        out: list[str] = []
        pages = self._c.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix)
        for page in pages:
            out += [o["Key"] for o in page.get("Contents", [])]
        return out

    def delete(self, key: str) -> None:
        self._c.delete_object(Bucket=self.bucket, Key=key)
