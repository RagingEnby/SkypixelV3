import atexit
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock, patch

if TYPE_CHECKING:
    from disnake.types.interactions import EditApplicationCommand

    from skypixel.clients.hypixel import SkyblockItem

TEST_STORAGE = tempfile.TemporaryDirectory(prefix="skypixel-tests-")
atexit.register(TEST_STORAGE.cleanup)
os.environ["SKYPIXEL_STORAGE_DIR"] = TEST_STORAGE.name

secrets = types.ModuleType("scrts")
setattr(secrets, "BOT_TOKEN", "test-token")  # noqa: B010
setattr(secrets, "MONGODB_URI", "mongodb://localhost:27017")  # noqa: B010
sys.modules["scrts"] = secrets

ITEMS: list[SkyblockItem] = [
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


def make_database():
    """Return a state database in a new temporary directory."""
    from skypixel.storage.database import Database

    return Database(Path(tempfile.mkdtemp(dir=TEST_STORAGE.name)) / "skypixel.db")


def fail_saves(database, *errors: BaseException | None):
    """Patch database saves to raise each error in turn, then save normally.

    None in errors lets that save go through.
    """
    original = database._save
    remaining = list(errors)

    def save(*args):
        if remaining:
            error = remaining.pop(0)
            if error is not None:
                raise error
        return original(*args)

    return patch.object(database, "_save", side_effect=save)


def queued_alerts(database) -> list:
    """Return the alerts waiting in the outbox, oldest first."""
    return [pending.alert for pending in database._due_alerts(float("inf"))]


def make_bot(**kwargs) -> Mock:
    """Return a mock bot with the test settings and an empty state database."""
    kwargs.setdefault("database", make_database())
    return Mock(settings=SETTINGS, **kwargs)


def make_inter(**kwargs: object) -> Mock:
    """Return a mock command interaction that has not been answered yet."""
    inter = Mock(
        send=AsyncMock(),
        response=Mock(
            is_done=Mock(return_value=False),
            send_message=AsyncMock(),
            defer=AsyncMock(),
        ),
    )
    inter.configure_mock(**kwargs)
    return inter


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


def command_schema() -> list[EditApplicationCommand]:
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
