import atexit
import os
import tempfile
from contextlib import nullcontext
from unittest.mock import Mock, patch

TEST_STORAGE = tempfile.TemporaryDirectory(prefix="skypixel-tests-")
atexit.register(TEST_STORAGE.cleanup)
os.environ["SKYPIXEL_STORAGE_DIR"] = TEST_STORAGE.name
os.environ["SKYPIXEL_BOT_TOKEN"] = "test-token"
os.environ["SKYPIXEL_MONGODB_URI"] = "mongodb://localhost:27017"

ITEMS = [
    {
        "id": "TEST_MEMENTO",
        "name": "Test Memento",
        "category": "MEMENTO",
        "material": "PAPER",
    },
    {
        "id": "TEST_HELMET",
        "name": "Test Helmet",
        "material": "LEATHER_HELMET",
        "category": "HELMET",
        "color": "1,2,3",
    },
]


from skypixel.settings import Settings  # noqa: E402

SETTINGS = Settings.load()


def make_bot(**kwargs) -> Mock:
    """Return a mock bot that carries the test settings."""
    kwargs.setdefault("notifications", Mock(event=Mock(return_value=nullcontext())))
    return Mock(settings=SETTINGS, **kwargs)


with patch(
    "curl_cffi.AsyncSession",
    side_effect=AssertionError("Imports must not open a client."),
):
    from skypixel.clients import hypixel

    hypixel.initialize(ITEMS)


def command_schema():
    import asyncio

    import disnake
    from disnake.ext import commands

    loop = asyncio.new_event_loop()
    bot = commands.InteractionBot(
        loop=loop,
        intents=disnake.Intents.none(),
        command_sync_flags=commands.CommandSyncFlags.none(),
    )
    try:
        from skypixel.commands.itemdb import ItemDBCog
        from skypixel.trackers.ranktracker import RankTrackerCog

        for cog_type in (ItemDBCog, RankTrackerCog):
            bot.add_cog(cog_type.__new__(cog_type))
        return sorted(
            (command.body.to_dict() for command in bot.slash_commands),
            key=lambda command: command["name"],
        )
    finally:
        loop.run_until_complete(bot.close())
        loop.close()
