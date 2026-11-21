import asyncio
import logging
import signal
from contextlib import suppress
from pathlib import Path
from typing import Any

import disnake
from disnake.ext import commands

from skypixel import checks, constants, error_inbox_client
from skypixel.clients import http, hypixel, mojang
from skypixel.commands import owner
from skypixel.logging import configure_logging
from skypixel.settings import ConfigurationError, Settings
from skypixel.storage.notifications import NotificationOutbox

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SkypixelBot(commands.InteractionBot):
    def __init__(self, settings: Settings, **kwargs):
        self.settings = settings
        intents = disnake.Intents.default()
        intents.members = True
        kwargs.setdefault("chunk_guilds_at_startup", False)
        super().__init__(intents=intents, owner_id=constants.OWNER_ID, **kwargs)
        self._close_lock = asyncio.Lock()
        self._resources_closed = False
        self.notifications = NotificationOutbox(
            self, settings.storage_dir / "notifications.json"
        )
        self._notification_task: asyncio.Task | None = None

    async def close(self) -> None:
        async with self._close_lock:
            if self._resources_closed:
                return
            self._resources_closed = True
            try:
                results = await asyncio.gather(
                    *(
                        cog.close()
                        for cog in self.cogs.values()
                        if callable(getattr(cog, "close", None))
                    ),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        logger.error("A cog failed to close.", exc_info=result)
                if self._notification_task is not None:
                    self._notification_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._notification_task
                results = await asyncio.gather(
                    mojang.close(), http.close(), return_exceptions=True
                )
                for result in results:
                    if isinstance(result, BaseException):
                        logger.error("A client failed to close.", exc_info=result)
            finally:
                await super().close()
            logger.info("The bot has shut down.")

    async def on_error(self, event_method: str, *args: Any, **kwargs: Any) -> None:
        # disnake prints unhandled event errors to stderr. Logging them lets the
        # log file and the error inbox see them.
        logger.exception("The %s event failed.", event_method)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s.", self.user)
        if not self._resources_closed and (
            self._notification_task is None or self._notification_task.done()
        ):
            self._notification_task = asyncio.create_task(
                self.notifications.run(), name="skypixel-notifications"
            )


def load_cogs() -> list[type[commands.Cog]]:
    """Import the cogs. Call this after hypixel.load_items().

    itemdb reads the memento list when it is imported.
    """
    if not hypixel.MEMENTOS:
        raise RuntimeError("Load the item catalog before importing the cogs.")
    from skypixel.commands.guild import GuildCog
    from skypixel.commands.itemdb import ItemDBCog
    from skypixel.commands.logger import LoggerCog
    from skypixel.trackers.alphatracker import AlphaTrackerCog
    from skypixel.trackers.auctionhouse import AuctionTrackerCog
    from skypixel.trackers.firesaletracker import FireSaleTrackerCog
    from skypixel.trackers.jobtracker import JobTrackerCog
    from skypixel.trackers.motdtracker import MotdTrackerCog
    from skypixel.trackers.ranktracker import RankTrackerCog
    from skypixel.trackers.status import StatusUpdaterCog
    from skypixel.trackers.versiontracker import VersionTrackerCog
    from skypixel.trackers.zonetracker import ZoneTrackerCog

    return [
        AlphaTrackerCog,
        AuctionTrackerCog,
        FireSaleTrackerCog,
        GuildCog,
        ItemDBCog,
        LoggerCog,
        MotdTrackerCog,
        RankTrackerCog,
        StatusUpdaterCog,
        VersionTrackerCog,
        ZoneTrackerCog,
        JobTrackerCog,
    ]


def create_bot(settings: Settings, **kwargs) -> SkypixelBot:
    bot = SkypixelBot(settings, **kwargs)
    for cog in load_cogs():
        bot.add_cog(cog(bot))
    owner.register(bot)

    @bot.application_command_check()
    async def patron_only_check(inter: disnake.Interaction):
        return await checks.patron_only_check(bot, inter)

    return bot


async def run() -> None:
    settings = Settings.load()
    settings.validate()
    secrets: tuple[str, ...] = (settings.bot_token, settings.mongodb_uri)
    configure_logging(settings.storage_dir, secrets=secrets)
    # Send every ERROR log to the shared T3 error inbox (~/error-inbox).
    error_inbox_client.install(
        "skypixel",
        project_root=PROJECT_ROOT,
        secrets=secrets,
        loggers=("", "disnake"),
    )
    bot = None
    shutdown_task = None
    installed_signals = []
    loop = asyncio.get_running_loop()
    try:
        await hypixel.load_items(settings.storage_dir)
        bot = create_bot(settings)

        def stop() -> None:
            nonlocal shutdown_task
            if shutdown_task is None:
                shutdown_task = asyncio.create_task(
                    bot.close(), name="skypixel-shutdown"
                )

        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop)
            except NotImplementedError:
                continue
            installed_signals.append(signum)
        await bot.start(settings.bot_token)
    finally:
        for signum in installed_signals:
            loop.remove_signal_handler(signum)
        if shutdown_task is not None:
            await shutdown_task
        if bot is not None:
            await bot.close()
        else:
            await http.close()


def main() -> None:
    try:
        asyncio.run(run())
    except ConfigurationError as error:
        raise SystemExit(str(error)) from error
    except KeyboardInterrupt:
        pass
