"""Bounded blocking work without a task queue or external worker."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from ..models import ApiError


class Task:
    def __init__(self):
        self.connection = None
        self.cancelled = threading.Event()
        self.lock = threading.Lock()

    def attach(self, connection):
        with self.lock:
            self.connection = connection
            if self.cancelled.is_set():
                connection.interrupt()

    def interrupt(self):
        self.cancelled.set()
        with self.lock:
            if self.connection is not None:
                self.connection.interrupt()

    def detach(self):
        with self.lock:
            self.connection = None


class Execution:
    def __init__(self, capacity=2):
        self.capacity = capacity
        self.active = 0
        self.pool = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="analysis")

    async def run(self, function, *args, timeout=30):
        if self.active >= self.capacity:
            raise ApiError("The server is busy. Please try again shortly.", 429)
        self.active += 1
        task = Task()
        future = asyncio.get_running_loop().run_in_executor(self.pool, function, task, *args)
        future.add_done_callback(lambda _future: self.release())
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except (TimeoutError, asyncio.CancelledError) as error:
            task.interrupt()
            try:
                await asyncio.shield(future)
            except Exception:
                pass
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ApiError(
                "This calculation took too long. Try a smaller or simpler query.", 408
            ) from None

    def release(self):
        self.active -= 1

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
