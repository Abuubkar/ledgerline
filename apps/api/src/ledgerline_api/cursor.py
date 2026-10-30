"""Opaque, signed keyset cursors: the position of the last row on a page plus the filters it was issued for.

Signing stops clients from forging positions; binding the filters stops a cursor from one query being reused
with another, which would silently skip or repeat rows. See docs/adr/0006.
"""

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime


class InvalidCursor(ValueError):
    pass


@dataclass(frozen=True)
class Position:
    created_at: datetime
    id: uuid.UUID


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _filters_key(filters: dict[str, str | None]) -> str:
    return json.dumps(filters, sort_keys=True, separators=(",", ":"))


def _sign(payload: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode(), payload, hashlib.sha256).digest()[:16]


def encode(position: Position, filters: dict[str, str | None], secret: str) -> str:
    payload = json.dumps(
        {"t": position.created_at.isoformat(), "i": str(position.id), "f": _filters_key(filters)},
        separators=(",", ":"),
    ).encode()
    return f"{_b64(payload)}.{_b64(_sign(payload, secret))}"


def decode(cursor: str, filters: dict[str, str | None], secret: str) -> Position:
    try:
        payload_part, signature_part = cursor.split(".")
        payload, signature = _unb64(payload_part), _unb64(signature_part)
    except ValueError:
        raise InvalidCursor("malformed cursor") from None

    if not hmac.compare_digest(signature, _sign(payload, secret)):
        raise InvalidCursor("cursor signature does not match")

    data = json.loads(payload)
    if data["f"] != _filters_key(filters):
        raise InvalidCursor("cursor was issued for different filters")
    return Position(created_at=datetime.fromisoformat(data["t"]), id=uuid.UUID(data["i"]))
