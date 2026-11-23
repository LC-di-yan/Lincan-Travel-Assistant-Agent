"""Bound concurrent synchronous searches without blocking the event loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, local


class SearchBusy(RuntimeError):
    pass


class SearchExecutor:
    def __init__(self, max_workers: int = 4):
        self._available = BoundedSemaphore(max_workers)
        self._threads = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="aligo-search")

    async def run(self, action, timeout: float):
        if not self._available.acquire(blocking=False):
            raise SearchBusy("搜索任务繁忙")
        try:
            future = self._threads.submit(action)
        except BaseException:
            self._available.release()
            raise
        # The slot is held until the real worker exits, even after an HTTP
        # disconnect or an asyncio timeout; no unbounded queue can form.
        future.add_done_callback(lambda completed: self._available.release())
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)

    def close(self):
        self._threads.shutdown(wait=False, cancel_futures=True)


_executor = None
_worker = local()


def search_client(factory, timeout: int):
    if getattr(_worker, "factory", None) is not factory:
        _worker.client = factory(timeout=timeout)
        _worker.factory = factory
    return _worker.client


async def run_search(action, timeout: float):
    global _executor
    if _executor is None:
        _executor = SearchExecutor()
    return await _executor.run(action, timeout)


def close_search_executor():
    global _executor
    if _executor is not None:
        _executor.close()
        _executor = None
