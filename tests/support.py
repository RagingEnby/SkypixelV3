import os
import sys
import tempfile
import types
from unittest.mock import Mock, patch

TEST_STORAGE = tempfile.TemporaryDirectory(prefix="skypixel-tests-")
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


with patch("requests.get", side_effect=AssertionError("Imports must not fetch data.")):
    from modules import colors, hypixel, utils

    hypixel.initialize(ITEMS)
    import cogs
    from cogs import itemdb, ranktracker


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
        for name in ("ItemDBCog", "RankTrackerCog"):
            cog = getattr(cogs, name).__new__(getattr(cogs, name))
            bot.add_cog(cog)
        return sorted(
            (command.body.to_dict() for command in bot.slash_commands),
            key=lambda command: command["name"],
        )
    finally:
        loop.run_until_complete(bot.close())
        loop.close()
