import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from disnake.ext import commands

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


class PollingCog(commands.Cog):
    """Run one polling task across Discord reconnects and await it on close."""

    interval: float = 60

    def __init__(self, bot: SkypixelBot) -> None:
        self.bot: SkypixelBot = bot
        self.task: asyncio.Task[None] | None = None
        self._close_lock: asyncio.Lock = asyncio.Lock()
        self._closed: bool = False
        self._logger: logging.Logger = logging.getLogger(type(self).__module__)

    async def poll(self) -> float | None:
        raise NotImplementedError

    async def main(self) -> None:
        while True:
            delay: float | None
            try:
                delay = await self.poll()
                delay = self.interval if delay is None else max(float(delay), 1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("The %s poll failed.", type(self).__name__)
                delay = self.interval
            await asyncio.sleep(delay)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self._closed and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self.main(), name=type(self).__name__)

    async def close_resources(self) -> None:
        pass

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self.task is not None:
                    self.task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self.task
            finally:
                self.task = None
                await self.close_resources()
