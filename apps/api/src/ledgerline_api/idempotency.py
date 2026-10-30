"""Idempotency-Key handling, following draft-ietf-httpapi-idempotency-key-header-08. See docs/adr/0005.

`decide` holds the rules and is pure, so it is unit-tested. `claim`, `complete` and `release` are the
database steps around it.
"""

import enum
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ledgerline_api.db import IdempotencyKey


class Decision(enum.Enum):
    PROCEED = "proceed"  # first time we see this key (or the old claim expired/was abandoned)
    REPLAY = "replay"  # same key, same request, finished: return the stored response
    REUSED = "reused"  # same key, different request: 422
    IN_PROGRESS = "in_progress"  # same key, same request, still running: 409


@dataclass
class KeyState:
    request_hash: str
    response_status: int | None
    locked_at: datetime
    expires_at: datetime


def request_fingerprint(files: list[tuple[str, str, bytes]]) -> str:
    """Hash of (filename, content type, content) per file, in order. Multipart boundaries are random, so the
    raw body can't be hashed."""
    digest = hashlib.sha256()
    for filename, content_type, content in files:
        digest.update(f"{filename}\0{content_type}\0{hashlib.sha256(content).hexdigest()}\n".encode())
    return digest.hexdigest()


def decide(state: KeyState | None, request_hash: str, now: datetime, lock_timeout: timedelta) -> Decision:
    if state is None or state.expires_at <= now:
        return Decision.PROCEED
    if state.request_hash != request_hash:
        return Decision.REUSED
    if state.response_status is not None:
        return Decision.REPLAY
    if now - state.locked_at > lock_timeout:
        # The request that claimed the key died without finishing; let this retry take over.
        return Decision.PROCEED
    return Decision.IN_PROGRESS


async def claim(
    session: AsyncSession, key: uuid.UUID, request_hash: str, now: datetime, ttl: timedelta, lock_timeout: timedelta
) -> tuple[Decision, IdempotencyKey | None]:
    """Try to take the key. The INSERT ... ON CONFLICT is what makes two concurrent requests safe: exactly one
    insert wins, and the other sees the winner's row."""
    inserted = await session.execute(
        insert(IdempotencyKey)
        .values(key=key, request_hash=request_hash, locked_at=now, expires_at=now + ttl)
        .on_conflict_do_nothing(index_elements=[IdempotencyKey.key])
        .returning(IdempotencyKey.key)
    )
    if inserted.scalar_one_or_none() is not None:
        await session.commit()
        return Decision.PROCEED, None

    row = (await session.execute(select(IdempotencyKey).where(IdempotencyKey.key == key).with_for_update())).scalar_one()
    state = KeyState(row.request_hash, row.response_status, row.locked_at, row.expires_at)
    decision = decide(state, request_hash, now, lock_timeout)
    if decision is Decision.PROCEED:
        # Expired or abandoned: re-take it under the row lock so a third request can't take it too.
        row.request_hash, row.locked_at, row.expires_at = request_hash, now, now + ttl
        row.response_status = row.response_body = None
        await session.commit()
        return decision, None
    await session.commit()
    return decision, row


async def complete(session: AsyncSession, key: uuid.UUID, status: int, body: dict) -> None:
    row = await session.get(IdempotencyKey, key)
    if row is not None:
        row.response_status, row.response_body = status, body
        await session.commit()


async def release(session: AsyncSession, key: uuid.UUID) -> None:
    """Drop a claim after an unexpected error, so the client can retry with the same key."""
    await session.rollback()
    await session.execute(delete(IdempotencyKey).where(IdempotencyKey.key == key))
    await session.commit()
