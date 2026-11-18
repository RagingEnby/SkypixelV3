import asyncio
import logging
from contextlib import suppress
from functools import wraps

from disnake.ext import commands

from skypixel.storage.json_store import JsonWrapper
from skypixel.storage.notifications import NotificationOutbox, notification_fingerprint


class PollingCog(commands.Cog):
    """Run one polling task across Discord reconnects and await it on close."""

    interval: float = 60

    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self._close_lock = asyncio.Lock()
        self._closed = False
        self._logger = logging.getLogger(type(self).__module__)
        if isinstance(getattr(bot, "notifications", None), NotificationOutbox):
            poll = self.poll

            @wraps(poll)
            async def poll_with_notifications():
                state = getattr(self, "data", None)
                version = notification_fingerprint(
                    {
                        "state": state.to_dict()
                        if isinstance(state, JsonWrapper)
                        else {
                            "active": getattr(self, "last_scanned_active", None),
                            "ended": getattr(self, "last_scanned_ended", None),
                        }
                    },
                )
                async with bot.notifications.event(type(self).__name__, version):
                    return await poll()

            self.poll = poll_with_notifications

    async def poll(self) -> float | None:
        raise NotImplementedError

    async def main(self) -> None:
        while True:
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
