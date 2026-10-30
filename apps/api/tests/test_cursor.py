import uuid
from datetime import UTC, datetime

import pytest

from ledgerline_api import cursor

SECRET = "test-secret"
POSITION = cursor.Position(datetime(2026, 10, 30, 9, 0, tzinfo=UTC), uuid.UUID("01a18bd9-0d75-7cee-8dc0-a78f27a51a41"))
NO_FILTERS = {"status": None, "created_after": None}


def test_round_trip_returns_the_same_position():
    token = cursor.encode(POSITION, NO_FILTERS, SECRET)
    assert cursor.decode(token, NO_FILTERS, SECRET) == POSITION


def test_edited_payload_is_rejected():
    _, signature = cursor.encode(POSITION, NO_FILTERS, SECRET).split(".")
    forged = cursor.encode(
        cursor.Position(POSITION.created_at, uuid.UUID(int=0)), NO_FILTERS, "attacker-guess"
    ).split(".")[0]
    with pytest.raises(cursor.InvalidCursor, match="signature"):
        cursor.decode(f"{forged}.{signature}", NO_FILTERS, SECRET)


def test_cursor_signed_with_another_secret_is_rejected():
    token = cursor.encode(POSITION, NO_FILTERS, "old-secret")
    with pytest.raises(cursor.InvalidCursor):
        cursor.decode(token, NO_FILTERS, SECRET)


def test_cursor_reused_with_different_filters_is_rejected():
    # Reusing a cursor under other filters would silently skip or repeat rows.
    token = cursor.encode(POSITION, NO_FILTERS, SECRET)
    with pytest.raises(cursor.InvalidCursor, match="different filters"):
        cursor.decode(token, {"status": "failed", "created_after": None}, SECRET)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "!!!.???"])
def test_malformed_cursors_are_rejected(garbage):
    with pytest.raises(cursor.InvalidCursor):
        cursor.decode(garbage, NO_FILTERS, SECRET)
