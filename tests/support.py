import atexit
import os
import sys
import tempfile
import types
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock, patch

TEST_STORAGE = tempfile.TemporaryDirectory(prefix="skypixel-tests-")
atexit.register(TEST_STORAGE.cleanup)
os.environ["SKYPIXEL_STORAGE_DIR"] = TEST_STORAGE.name

secrets = types.ModuleType("scrts")
secrets.BOT_TOKEN = "test-token"
secrets.MONGODB_URI = "mongodb://localhost:27017"
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


from skypixel.services import Services  # noqa: E402
from skypixel.settings import Settings  # noqa: E402

SETTINGS = Settings.load()


def make_bot(**kwargs) -> Mock:
    """Return a mock bot that carries the test settings."""
    kwargs.setdefault("notifications", Mock(event=Mock(return_value=nullcontext())))
    kwargs.setdefault("services", Services(SETTINGS))
    return Mock(settings=SETTINGS, **kwargs)


def make_inter(**kwargs) -> Mock:
    """Return a mock command interaction that has not been answered yet."""
    return Mock(
        send=AsyncMock(),
        response=Mock(
            is_done=Mock(return_value=False),
            send_message=AsyncMock(),
            defer=AsyncMock(),
        ),
        **kwargs,
    )


def error_title(inter: Mock) -> str:
    """Return the title of the private error sent to a make_inter() mock."""
    call = inter.response.send_message.call_args
    assert call.kwargs["ephemeral"]
    return call.kwargs["embed"].title


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
