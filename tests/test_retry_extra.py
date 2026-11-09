"""retry.py phải khớp bảng timeout/retry trong docs/c4-model.md."""

from datetime import timedelta

import pytest

from ingest.core import errors as E
from ingest.core import retry as R

S = timedelta(seconds=1)
M = timedelta(minutes=1)

# (policy, timeout, attempts, non_retryable) theo từng dòng của bảng spec
TABLE = {
    "update_status": (R.RETRY_STATUS, R.T_STATUS, 10, [], 10 * S),
    "detect_format": (
        R.RETRY_DETECT, R.T_DETECT, 3, [E.UNSUPPORTED_FORMAT, E.FILE_CORRUPTED], 30 * S,
    ),
    "parse_document": (
        R.RETRY_PARSE, R.T_PARSE, 3, [E.FILE_CORRUPTED, E.PASSWORD_PROTECTED], 10 * M,
    ),
    "ocr_pages": (R.RETRY_OCR, R.T_OCR, 5, [], 15 * M),
    "finalize_markdown": (R.RETRY_FINALIZE, R.T_FINALIZE, 3, [E.EMPTY_DOCUMENT], 2 * M),
    "chunk_markdown": (R.RETRY_CHUNK, R.T_CHUNK, 3, [], 2 * M),
    "embed_and_upsert": (R.RETRY_EMBED, R.T_EMBED, 8, [E.EMBED_INPUT_TOO_LONG], 2 * M),
    "cleanup_old_chunks": (R.RETRY_CLEANUP, R.T_CLEANUP, 5, [], 1 * M),
}  # fmt: skip


@pytest.mark.parametrize("name", list(TABLE))
def test_activity_policy_matches_spec_table(name):
    policy, timeout, attempts, non_retryable, expected_timeout = TABLE[name]
    assert policy.maximum_attempts == attempts
    assert sorted(policy.non_retryable_error_types or []) == sorted(non_retryable)
    assert timeout == expected_timeout


def test_detect_backoff_is_2s_times_2():
    assert R.RETRY_DETECT.initial_interval == 2 * S
    assert R.RETRY_DETECT.backoff_coefficient == 2


def test_embed_backoff_capped_at_5_minutes_for_429():
    assert R.RETRY_EMBED.maximum_interval == 5 * M
    assert R.RETRY_EMBED.backoff_coefficient > 1


def test_heartbeat_one_minute_and_execution_timeout_six_hours():
    assert R.HEARTBEAT == 1 * M
    assert R.EXECUTION_TIMEOUT == timedelta(hours=6)


def test_every_spec_error_code_is_registered_as_non_retryable():
    for code in (
        E.UNSUPPORTED_FORMAT, E.FILE_CORRUPTED, E.PASSWORD_PROTECTED,
        E.EMPTY_DOCUMENT, E.EMBED_INPUT_TOO_LONG,
    ):  # fmt: skip
        assert code in E.NON_RETRYABLE_CODES
        assert code == code.upper()


def test_to_application_error_is_non_retryable_with_code_as_type():
    err = E.to_application_error(E.IngestError(E.FILE_CORRUPTED, "hỏng"))
    assert err.type == E.FILE_CORRUPTED and err.non_retryable and "hỏng" in str(err)
