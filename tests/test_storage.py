"""Storage: MemoryStorage và S3Storage (client boto3 giả lập bằng botocore Stubber)."""

import io

import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from ingest.core.storage import MemoryStorage, S3Storage

BUCKET = "ingest"


def test_memory_storage_roundtrip():
    st = MemoryStorage()
    data = bytearray(b"abc")
    st.put("docs/a", data)
    data[0] = ord("z")  # bản lưu không bị ảnh hưởng khi buffer gốc đổi
    assert st.get("docs/a") == b"abc"
    assert st.exists("docs/a") and not st.exists("docs/b")
    st.put("docs/c", b"1")
    st.put("other/x", b"2")
    assert st.list_keys("docs/") == ["docs/a", "docs/c"]
    st.delete("docs/a")
    st.delete("docs/a")  # xoá lần hai không lỗi
    assert not st.exists("docs/a")
    with pytest.raises(FileNotFoundError):
        st.get("docs/a")


@pytest.fixture
def s3():
    st = S3Storage("http://minio:9000", "ak", "sk", BUCKET)
    with Stubber(st._c) as stub:
        yield st, stub
        stub.assert_no_pending_responses()


def test_s3_client_uses_path_style():
    st = S3Storage("http://minio:9000", "ak", "sk", BUCKET, region="ap-southeast-1")
    assert st.bucket == BUCKET
    assert st._c.meta.endpoint_url == "http://minio:9000"
    assert st._c.meta.region_name == "ap-southeast-1"
    assert st._c.meta.config.s3["addressing_style"] == "path"


def test_ensure_bucket_exists_does_nothing(s3):
    st, stub = s3
    stub.add_response("head_bucket", {}, {"Bucket": BUCKET})
    st.ensure_bucket()


@pytest.mark.parametrize("code", ["404", "NoSuchBucket", "403"])
def test_ensure_bucket_creates_when_missing(s3, code):
    st, stub = s3
    stub.add_client_error("head_bucket", service_error_code=code, http_status_code=404)
    stub.add_response("create_bucket", {}, {"Bucket": BUCKET})
    st.ensure_bucket()


def test_ensure_bucket_reraises_other_errors(s3):
    from botocore.exceptions import ClientError

    st, stub = s3
    stub.add_client_error("head_bucket", service_error_code="500", http_status_code=500)
    with pytest.raises(ClientError):
        st.ensure_bucket()


def test_put_uploads(monkeypatch):
    st = S3Storage("http://minio:9000", "ak", "sk", BUCKET)
    seen = {}

    def fake_upload(fileobj, bucket, key):
        seen.update(data=fileobj.read(), bucket=bucket, key=key)

    monkeypatch.setattr(st._c, "upload_fileobj", fake_upload)
    st.put("k", b"noi dung")
    assert seen == {"data": b"noi dung", "bucket": BUCKET, "key": "k"}


def test_get_returns_body(s3):
    st, stub = s3
    body = StreamingBody(io.BytesIO(b"xyz"), 3)
    stub.add_response("get_object", {"Body": body}, {"Bucket": BUCKET, "Key": "k"})
    assert st.get("k") == b"xyz"


@pytest.mark.parametrize("code", ["NoSuchKey", "404"])
def test_get_missing_raises_file_not_found(s3, code):
    st, stub = s3
    stub.add_client_error("get_object", service_error_code=code, http_status_code=404)
    with pytest.raises(FileNotFoundError):
        st.get("k")


def test_get_other_error_reraised(s3):
    from botocore.exceptions import ClientError

    st, stub = s3
    stub.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(ClientError):
        st.get("k")


def test_exists(s3):
    st, stub = s3
    stub.add_response("head_object", {}, {"Bucket": BUCKET, "Key": "a"})
    stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
    assert st.exists("a") is True
    assert st.exists("b") is False


def test_list_keys_paginates(s3):
    st, stub = s3
    stub.add_response(
        "list_objects_v2",
        {
            "Contents": [{"Key": "p/1"}, {"Key": "p/2"}],
            "IsTruncated": True,
            "NextContinuationToken": "t",
        },
        {"Bucket": BUCKET, "Prefix": "p/"},
    )
    stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "p/3"}], "IsTruncated": False},
        {"Bucket": BUCKET, "Prefix": "p/", "ContinuationToken": "t"},
    )
    assert st.list_keys("p/") == ["p/1", "p/2", "p/3"]


def test_list_keys_empty(s3):
    st, stub = s3
    stub.add_response("list_objects_v2", {"IsTruncated": False}, {"Bucket": BUCKET, "Prefix": ANY})
    assert st.list_keys("none/") == []


def test_delete(s3):
    st, stub = s3
    stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": "k"})
    st.delete("k")
