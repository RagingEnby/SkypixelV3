import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


class SharedRequests[T]:
    """Run one request per key and share its result with every caller.

    A caller that is cancelled does not cancel the request for the others.
    """

    def __init__(self, name: str) -> None:
        self.name: str = name
        self.tasks: dict[str, asyncio.Task[T]] = {}

    async def run(self, key: str, factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
        task: asyncio.Task[T] | None = self.tasks.get(key)
        if task is None:
            task = asyncio.create_task(factory(), name=f"{self.name}-{key}")
            self.tasks[key] = task
            task.add_done_callback(lambda finished: self._finish(key, finished))
        return await asyncio.shield(task)

    def _finish(self, key: str, task: asyncio.Task[T]) -> None:
        if self.tasks.get(key) is task:
            self.tasks.pop(key)
        if not task.cancelled():
            # Mark the error as retrieved so asyncio does not log it when no
            # caller is left to await the task.
            task.exception()

    async def close(self) -> None:
        tasks: list[asyncio.Task[T]] = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
