from datetime import UTC, datetime, timedelta

import pytest

from ledgerline_api.idempotency import Decision, KeyState, decide, request_fingerprint

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
LOCK_TIMEOUT = timedelta(minutes=15)


def state(request_hash="h1", response_status=None, locked_ago=timedelta(seconds=5), expires_in=timedelta(hours=24)):
    return KeyState(request_hash, response_status, NOW - locked_ago, NOW + expires_in)


@pytest.mark.parametrize(
    ("key_state", "request_hash", "expected"),
    [
        (None, "h1", Decision.PROCEED),
        (state(response_status=201), "h1", Decision.REPLAY),
        (state(response_status=201), "h2", Decision.REUSED),
        (state(), "h2", Decision.REUSED),  # different body is rejected even while the first is running
        (state(), "h1", Decision.IN_PROGRESS),
        (state(locked_ago=timedelta(minutes=16)), "h1", Decision.PROCEED),  # first request died
        (state(response_status=201, expires_in=-timedelta(seconds=1)), "h2", Decision.PROCEED),  # expired key
    ],
    ids=["new", "replay", "reused-after-finish", "reused-while-running", "in-progress", "abandoned", "expired"],
)
def test_decision_rules(key_state, request_hash, expected):
    assert decide(key_state, request_hash, NOW, LOCK_TIMEOUT) is expected


def test_fingerprint_changes_with_content_name_and_order():
    a = ("a.pdf", "application/pdf", b"one")
    b = ("b.pdf", "application/pdf", b"two")
    base = request_fingerprint([a, b])
    assert request_fingerprint([a, b]) == base
    assert request_fingerprint([b, a]) != base
    assert request_fingerprint([("a.pdf", "application/pdf", b"ONE"), b]) != base
    assert request_fingerprint([("renamed.pdf", "application/pdf", b"one"), b]) != base
