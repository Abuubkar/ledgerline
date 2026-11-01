"""A counting semaphore in Redis with leased slots, capping model calls across every worker process.

Each holder is a member of a sorted set scored by its lease expiry. Acquiring first drops expired members, so a
worker killed mid-call can't hold its slot for longer than one lease. Both steps run in one Lua script, which
Redis executes atomically. Holders renew a short lease while their call runs, so the lease can be short (30 s)
without cutting off a long model call: with one slot, a crashed worker stalls extraction for at most one lease.
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis

from ledgerline_api import metrics
from ledgerline_api.errors import TransientError
from ledgerline_api.settings import settings

KEY = "ledgerline:llm-slots"

# Uses the Redis server's clock, so workers on machines with skewed clocks still agree on expiry.
_ACQUIRE = """
local key, lease_s, limit, token = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), ARGV[3]
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) < limit then
  redis.call('ZADD', key, now + lease_s, token)
  return 1
end
return 0
"""


async def try_acquire(client: redis.Redis, token: str, limit: int, lease_s: float) -> bool:
    return bool(await client.eval(_ACQUIRE, 1, KEY, lease_s, limit, token))


# A lapsed lease is never revived: expired members linger until the next acquire cleans them up, so the
# expiry has to be checked here, not just membership.
_RENEW = """
local key, lease_s, token = KEYS[1], tonumber(ARGV[1]), ARGV[2]
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local expires = redis.call('ZSCORE', key, token)
if expires and tonumber(expires) > now then
  redis.call('ZADD', key, 'XX', now + lease_s, token)
  return 1
end
return 0
"""


async def renew(client: redis.Redis, token: str, lease_s: float) -> bool:
    """Extend a held slot's lease. False if the slot already lapsed and may have been taken."""
    return bool(await client.eval(_RENEW, 1, KEY, lease_s, token))


async def _keep_renewing(client: redis.Redis, token: str) -> None:
    while True:
        await asyncio.sleep(settings.llm_slot_lease_s / 3)
        await renew(client, token, settings.llm_slot_lease_s)


async def release(client: redis.Redis, token: str) -> None:
    await client.zrem(KEY, token)


@asynccontextmanager
async def llm_slot(client: redis.Redis):
    """Wait for a free model slot, hold it for the call, always give it back."""
    token = uuid.uuid4().hex
    asked = time.monotonic()
    deadline = asked + settings.llm_slot_wait_s
    while not await try_acquire(client, token, settings.llm_max_concurrency, settings.llm_slot_lease_s):
        if time.monotonic() > deadline:
            metrics.slot_wait.record(time.monotonic() - asked, {"outcome": "timeout"})
            raise TransientError("llm_slot_timeout", f"no model slot free within {settings.llm_slot_wait_s}s")
        await asyncio.sleep(0.5)
    metrics.slot_wait.record(time.monotonic() - asked, {"outcome": "acquired"})
    renewer = asyncio.create_task(_keep_renewing(client, token))
    try:
        yield
    finally:
        renewer.cancel()
        await release(client, token)
