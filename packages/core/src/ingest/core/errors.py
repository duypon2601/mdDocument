"""Mã lỗi nghiệp vụ. Lỗi chạy lại vẫn hỏng thì raise non_retryable với type cố định."""

from temporalio.exceptions import ApplicationError

UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
FILE_CORRUPTED = "FILE_CORRUPTED"
PASSWORD_PROTECTED = "PASSWORD_PROTECTED"
EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
EMBED_INPUT_TOO_LONG = "EMBED_INPUT_TOO_LONG"
OCR_REJECTED = "OCR_REJECTED"

NON_RETRYABLE_CODES = frozenset(
    {
        UNSUPPORTED_FORMAT,
        FILE_CORRUPTED,
        PASSWORD_PROTECTED,
        EMPTY_DOCUMENT,
        EMBED_INPUT_TOO_LONG,
        OCR_REJECTED,
    }
)


class IngestError(Exception):
    """Lỗi thuần Python (dùng trong parser/module, không phụ thuộc Temporal)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def to_application_error(exc: IngestError) -> ApplicationError:
    return ApplicationError(str(exc), type=exc.code, non_retryable=True)
