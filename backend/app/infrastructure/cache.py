"""Redis cache of saved dashboards. Postgres is authoritative, including during outages."""

import asyncio
import hashlib
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from uuid import uuid4
from weakref import WeakValueDictionary

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

logger = logging.getLogger("analysis_api.cache")

# Tokens fence off a database read that finishes after a concurrent invalidation.
# All script keys are explicit, and the operations are atomic within Redis.
READ = """
local epoch = redis.call('GET', KEYS[1])
if not epoch then
    epoch = ARGV[1]
    redis.call('SET', KEYS[1], epoch)
end
local generation = redis.call('GET', KEYS[2])
if not generation then
    generation = ARGV[2]
    redis.call('SET', KEYS[2], generation, 'PX', ARGV[3])
end
local cached = redis.call('HMGET', KEYS[3], 'epoch', 'generation', 'value')
if cached[1] == epoch and cached[2] == generation then
    return {epoch, generation, cached[3]}
end
return {epoch, generation, false}
"""
FILL = """
if redis.call('GET', KEYS[1]) == ARGV[1]
    and redis.call('GET', KEYS[2]) == ARGV[2] then
    redis.call('HSET', KEYS[3], 'epoch', ARGV[1], 'generation', ARGV[2], 'value', ARGV[3])
    redis.call('PEXPIRE', KEYS[3], ARGV[4])
    return 1
end
return 0
"""


class DashboardCache:
    def __init__(self, url, *, namespace="data-analysis:v1", ttl=300, max_bytes=1_000_000):
        self.client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            max_connections=16,
            retry=Retry(NoBackoff(), 0),
            health_check_interval=30,
        )
        self.namespace, self.ttl_ms, self.max_bytes = namespace, max(1, math.ceil(ttl * 1000)), max_bytes
        self.epoch_key = f"{namespace}:epoch"
        self.locks = WeakValueDictionary()
        self.recovery_lock = asyncio.Lock()
        self.reset_required = True
        self.next_retry = 0.0
        self.hits = self.misses = self.errors = 0
        self.outage = False

    def _lock(self, owner, identity):
        return self.locks.setdefault((owner, identity), asyncio.Lock())

    def _keys(self, owner, identity, scope=""):
        # Hash identity components so delimiters cannot cause collisions between users.
        group = hashlib.sha256(json.dumps([owner, identity]).encode()).hexdigest()
        selection = hashlib.sha256(str(scope).encode()).hexdigest()
        base = f"{self.namespace}:{group}"
        return self.epoch_key, f"{base}:generation", f"{base}:{selection}"

    def _failed(self):
        self.errors += 1
        self.reset_required = True
        self.next_retry = time.monotonic() + 5
        if not self.outage:
            # Never log connection strings, credentials, tokens or cached data.
            logger.warning("dashboard_cache_unavailable fallback=postgres")
        self.outage = True

    async def _available(self):
        if time.monotonic() < self.next_retry:
            return False
        if not self.reset_required:
            return True
        async with self.recovery_lock:
            if time.monotonic() < self.next_retry:
                return False
            if self.reset_required:
                try:
                    # A restart or recovery discards responses whose invalidation may
                    # have been missed. Old payloads remain bounded by their own TTL.
                    await self.client.set(self.epoch_key, uuid4().hex)
                except (RedisError, OSError):
                    self._failed()
                    return False
                if self.outage:
                    logger.info("dashboard_cache_recovered")
                self.reset_required, self.outage = False, False
        return True

    async def initialize(self):
        await self._available()

    async def close(self):
        await self.client.aclose()

    async def invalidate(self, owner, identity):
        if not await self._available():
            return
        try:
            await self.client.set(
                self._keys(owner, identity)[1], uuid4().hex, px=self.ttl_ms * 2
            )
        except (RedisError, OSError):
            self._failed()

    @asynccontextmanager
    async def mutation(self, owner, identity):
        async with self._lock(owner, identity):
            # Invalidate before and after, even if the write fails or is cancelled.
            # Other processes cannot publish an older in-flight read afterwards.
            await self.invalidate(owner, identity)
            try:
                yield
            finally:
                await self.invalidate(owner, identity)

    async def read(self, key, loader):
        owner, identity, scope = key
        async with self._lock(owner, identity):
            tokens = None
            keys = self._keys(owner, identity, scope)
            if await self._available():
                try:
                    epoch, generation, raw = await self.client.eval(
                        READ, 3, *keys, uuid4().hex, uuid4().hex, self.ttl_ms * 2
                    )
                    tokens = epoch, generation
                    if raw is not None:
                        try:
                            value = json.loads(raw)
                            if not isinstance(value, dict):
                                raise ValueError("Invalid cached dashboard")
                        except (ValueError, TypeError):
                            await self.client.delete(keys[2])
                        else:
                            self.hits += 1
                            return value, True
                except (RedisError, OSError):
                    self._failed()
                    tokens = None
            self.misses += 1
            value = await loader()
            if value is not None and tokens is not None:
                raw = json.dumps(value, default=str)
                if len(raw.encode()) <= self.max_bytes:
                    try:
                        await self.client.eval(FILL, 3, *keys, *tokens, raw, self.ttl_ms)
                    except (RedisError, OSError):
                        self._failed()
            return value, False
