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


def fixture_response(url, **kwargs):
    data = (
        {"staff": [{"id": "abc", "name": "Player"}]}
        if url.endswith("/ranks")
        else {"items": ITEMS}
    )
    return Mock(json=Mock(return_value=data))


original_directory = os.getcwd()
sys.path.insert(0, original_directory)
try:
    os.chdir(TEST_STORAGE.name)
    with patch("requests.get", side_effect=fixture_response):
        import cogs
        from modules import colors, hypixel, utils
finally:
    os.chdir(original_directory)


def command_schema():
    import disnake
    from disnake.ext import commands

    bot = commands.InteractionBot(
        intents=disnake.Intents.none(),
        command_sync_flags=commands.CommandSyncFlags.none(),
    )
    for name in ("ItemDBCog", "RankTrackerCog"):
        cog = getattr(cogs, name).__new__(getattr(cogs, name))
        bot.add_cog(cog)
    return sorted(
        (command.body.to_dict() for command in bot.slash_commands),
        key=lambda command: command["name"],
    )
