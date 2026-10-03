import asyncio
import logging
import signal

import disnake
from disnake.ext import commands

from skypixel import checks, constants
from skypixel.clients import http, hypixel, mojang
from skypixel.commands import owner
from skypixel.logging import configure_logging
from skypixel.settings import ConfigurationError, settings

logger = logging.getLogger(__name__)


class SkypixelBot(commands.InteractionBot):
    def __init__(self, **kwargs):
        intents = disnake.Intents.default()
        intents.members = True
        super().__init__(intents=intents, owner_id=constants.OWNER_ID, **kwargs)
        self._close_lock = asyncio.Lock()
        self._resources_closed = False

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
                results = await asyncio.gather(
                    mojang.close(), http.close(), return_exceptions=True
                )
                for result in results:
                    if isinstance(result, BaseException):
                        logger.error("A client failed to close.", exc_info=result)
            finally:
                try:
                    await super().close()
                finally:
                    if constants.BOT is self:
                        constants.BOT = None
            logger.info("The bot has shut down.")

    async def on_ready(self) -> None:
        logger.info("Logged in as %s.", self.user)


def load_cogs() -> list[type[commands.Cog]]:
    """Import the cogs. Call this after hypixel.load_items().

    itemdb reads the memento list when it is imported.
    """
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
    from skypixel.trackers.wikitracker import WikiTrackerCog
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
        WikiTrackerCog,
        ZoneTrackerCog,
        JobTrackerCog,
    ]


def create_bot(**kwargs) -> SkypixelBot:
    bot = SkypixelBot(**kwargs)
    constants.BOT = bot
    for cog in load_cogs():
        bot.add_cog(cog(bot))
    owner.register(bot)

    @bot.application_command_check()
    async def patron_only_check(inter: disnake.Interaction):
        return await checks.patron_only_check(bot, inter)

    return bot


async def run() -> None:
    settings.validate()
    configure_logging(
        settings.storage_dir,
        secrets=(settings.bot_token, settings.mongodb_uri, *settings.proxies.values()),
    )
    bot = None
    shutdown_task = None
    installed_signals = []
    loop = asyncio.get_running_loop()
    try:
        await hypixel.load_items()
        bot = create_bot()

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
        bot = bot or constants.BOT
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
