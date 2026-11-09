"""Timeout/retry đúng bảng trong docs/c4-model.md."""

from datetime import timedelta

from temporalio.common import RetryPolicy

from ingest.core import errors as E

RETRY_SHORT = RetryPolicy(maximum_attempts=3)

RETRY_STATUS = RetryPolicy(maximum_attempts=10)
RETRY_DETECT = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2,
    non_retryable_error_types=[E.UNSUPPORTED_FORMAT, E.FILE_CORRUPTED],
)
RETRY_PARSE = RetryPolicy(
    maximum_attempts=3,
    non_retryable_error_types=[E.FILE_CORRUPTED, E.PASSWORD_PROTECTED],
)
RETRY_OCR = RetryPolicy(maximum_attempts=5)
RETRY_FINALIZE = RetryPolicy(maximum_attempts=3, non_retryable_error_types=[E.EMPTY_DOCUMENT])
RETRY_STATS = RetryPolicy(maximum_attempts=3)
RETRY_CHUNK = RetryPolicy(maximum_attempts=3)
RETRY_EMBED = RetryPolicy(
    maximum_attempts=8,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2,
    maximum_interval=timedelta(minutes=5),
    non_retryable_error_types=[E.EMBED_INPUT_TOO_LONG],
)
RETRY_CLEANUP = RetryPolicy(maximum_attempts=5)

T_STATUS = timedelta(seconds=10)
T_DETECT = timedelta(seconds=30)
T_PARSE = timedelta(minutes=10)
T_OCR = timedelta(minutes=15)
T_FINALIZE = timedelta(minutes=2)
T_STATS = timedelta(seconds=30)
T_CHUNK = timedelta(minutes=2)
T_EMBED = timedelta(minutes=2)
T_CLEANUP = timedelta(minutes=1)
HEARTBEAT = timedelta(minutes=1)
EXECUTION_TIMEOUT = timedelta(hours=6)
