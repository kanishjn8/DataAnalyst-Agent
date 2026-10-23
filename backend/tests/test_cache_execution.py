import asyncio
import time
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from app.config import Settings
from app.infrastructure.cache import FILL, DashboardCache
from app.infrastructure.execution import Execution
from app.models import ApiError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def caches():
    namespace = f"regression:{uuid4().hex}"
    instances = []

    async def create(**options):
        cache = DashboardCache(Settings().redis_url, namespace=namespace, **options)
        # Regression tests must exercise real Redis, never silently fall back.
        assert await cache.client.ping()
        await cache.initialize()
        instances.append(cache)
        return cache

    yield create
    if instances:
        client = instances[0].client
        keys = [key async for key in client.scan_iter(match=f"{namespace}:*")]
        if keys:
            await client.delete(*keys)
    for cache in instances:
        await cache.close()


@pytest.mark.anyio
async def test_cache_owner_scope_ttl_and_mutation(caches):
    cache = await caches()
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        return {"value": calls}

    key = ("alice", "a", "scope")
    assert not (await cache.read(key, load))[1]
    value, hit = await cache.read(key, load)
    assert hit and value == {"value": 1}
    value["value"] = "changed outside cache"
    assert (await cache.read(key, load))[0] == {"value": 1}
    assert (await cache.read(("bob", "a", "scope"), load))[0]["value"] == 2
    assert not (await cache.read(("alice", "a", "other-scope"), load))[1]
    async with cache.mutation("alice", "a"):
        pass
    assert not (await cache.read(key, load))[1]
    # Redis, rather than the Python process, owns expiration.
    assert 0 < await cache.client.pttl(cache._keys(*key)[2]) <= cache.ttl_ms
    await cache.client.pexpire(cache._keys(*key)[2], 1)
    await asyncio.sleep(0.02)
    assert not (await cache.read(key, load))[1]


@pytest.mark.anyio
async def test_shared_cache_and_invalidation_fences_late_fills(caches):
    first, second = await caches(), await caches()
    key = ("alice", "a", "scope")
    state = {"value": 1}

    async def load():
        return dict(state)

    await first.read(key, load)
    assert (await second.read(key, load))[1]
    await second.invalidate("alice", "a")
    started, finish = asyncio.Event(), asyncio.Event()

    async def old_read():
        snapshot = dict(state)
        started.set()
        await finish.wait()
        return snapshot

    pending = asyncio.create_task(first.read(key, old_read))
    await started.wait()
    async with second.mutation("alice", "a"):
        state["value"] = 2
    finish.set()
    assert (await pending)[0] == {"value": 1}
    # A read started before a write may finish with its snapshot, but must not
    # repopulate Redis with that snapshot after invalidation.
    assert await second.read(key, load) == ({"value": 2}, False)
    assert await first.read(key, load) == ({"value": 2}, True)


@pytest.mark.anyio
async def test_concurrent_misses_share_one_database_read(caches):
    cache = await caches()
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"value": calls}

    results = await asyncio.gather(*(cache.read(("alice", "a", "scope"), load) for _ in range(8)))
    assert calls == 1
    assert sum(hit for _, hit in results) == 7


@pytest.mark.anyio
async def test_outage_falls_back_and_recovery_drops_missed_invalidations(caches, monkeypatch):
    cache = await caches()
    key = ("alice", "a", "scope")
    state = {"value": 1}

    async def load():
        return dict(state)

    await cache.read(key, load)
    assert (await cache.read(key, load))[1]

    async def unavailable(*args, **kwargs):
        raise ConnectionError("test outage")

    with monkeypatch.context() as patch:
        patch.setattr(cache.client, "eval", unavailable)
        assert await cache.read(key, load) == ({"value": 1}, False)
        async with cache.mutation("alice", "a"):
            state["value"] = 2
        assert await cache.read(key, load) == ({"value": 2}, False)
    cache.next_retry = 0
    # The old Redis payload still exists; recovery must not return it.
    assert await cache.read(key, load) == ({"value": 2}, False)
    assert await cache.read(key, load) == ({"value": 2}, True)


@pytest.mark.anyio
async def test_oversized_corrupt_and_missing_responses(caches):
    cache = await caches(max_bytes=50)
    key = ("alice", "a", "scope")

    async def large():
        return {"value": "x" * 100}

    async def missing():
        return None

    async def small():
        return {"value": 1}

    assert not (await cache.read(key, large))[1]
    assert not await cache.client.exists(cache._keys(*key)[2])
    assert await cache.read(key, missing) == (None, False)
    await cache.read(key, small)
    await cache.client.hset(cache._keys(*key)[2], "value", "invalid json")
    assert await cache.read(key, small) == ({"value": 1}, False)
    assert await cache.read(key, small) == ({"value": 1}, True)


@pytest.mark.anyio
async def test_failed_write_invalidates_and_loader_errors_propagate(caches):
    cache = await caches()
    key = ("alice", "a", "scope")
    state = {"value": 1}

    async def load():
        return dict(state)

    await cache.read(key, load)
    with pytest.raises(RuntimeError, match="write failed"):
        async with cache.mutation("alice", "a"):
            state["value"] = 2
            raise RuntimeError("write failed")
    assert await cache.read(key, load) == ({"value": 2}, False)
    await cache.invalidate("alice", "a")

    async def failed_load():
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await cache.read(key, failed_load)


@pytest.mark.anyio
async def test_failed_fill_does_not_fail_the_request(caches, monkeypatch):
    cache = await caches()
    evaluate = cache.client.eval

    async def fail_fill(script, *args):
        if script == FILL:
            raise ConnectionError("test write failure")
        return await evaluate(script, *args)

    monkeypatch.setattr(cache.client, "eval", fail_fill)

    async def load():
        return {"value": 1}

    assert await cache.read(("alice", "a", "scope"), load) == ({"value": 1}, False)
    assert cache.errors == 1


@pytest.mark.anyio
async def test_backend_cache_starts_when_redis_is_unavailable():
    cache = DashboardCache("redis://127.0.0.1:1", namespace="unavailable-test")
    try:
        await cache.initialize()

        async def load():
            return {"value": 1}

        assert await cache.read(("alice", "a", "scope"), load) == ({"value": 1}, False)
        assert cache.errors == 1
    finally:
        await cache.close()


@pytest.mark.anyio
async def test_execution_busy_and_timeout_wait_for_actual_stop():
    execution = Execution(capacity=1)

    def work(task):
        while not task.cancelled.is_set():
            time.sleep(0.005)
        time.sleep(0.02)

    running = asyncio.create_task(execution.run(work, timeout=0.03))
    await asyncio.sleep(0.01)
    with pytest.raises(ApiError, match="busy"):
        await execution.run(work)
    with pytest.raises(ApiError, match="too long"):
        await running
    assert execution.active == 0
    execution.close()
