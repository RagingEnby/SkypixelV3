import atexit
import os
import sys
import tempfile
import types
from unittest.mock import patch

TEST_STORAGE = tempfile.TemporaryDirectory(prefix="skypixel-tests-")
atexit.register(TEST_STORAGE.cleanup)
os.environ["SKYPIXEL_STORAGE_DIR"] = TEST_STORAGE.name

secrets = types.ModuleType("scrts")
secrets.BOT_TOKEN = "test-token"
secrets.MONGODB_URI = "mongodb://localhost:27017"
secrets.PROXIES = {"http": "http://localhost:8080"}
sys.modules["scrts"] = secrets

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
