import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from disnake.ext import commands

from skypixel import app, checks, constants, settings
from skypixel.clients import hypixel
from tests import support


class SettingsTests(unittest.TestCase):
    def test_environment_overrides_legacy_credentials(self):
        legacy = SimpleNamespace(
            BOT_TOKEN="old-token",
            MONGODB_URI="old-uri",
            PROXIES={"http": "old-proxy", "sock5": "socks"},
        )
        with (
            patch.dict(
                os.environ,
                {
                    "SKYPIXEL_BOT_TOKEN": "new-token",
                    "SKYPIXEL_MONGODB_URI": "new-uri",
                    "SKYPIXEL_HTTP_PROXY": "new-proxy",
                    "SKYPIXEL_STORAGE_DIR": "custom",
                },
                clear=True,
            ),
            patch.object(settings, "import_module", return_value=legacy),
        ):
            loaded = settings.Settings.load()
        self.assertEqual(loaded.bot_token, "new-token")
        self.assertEqual(loaded.mongodb_uri, "new-uri")
        self.assertEqual(loaded.proxies, {"http": "new-proxy", "sock5": "socks"})
        self.assertEqual(loaded.storage_dir, Path("custom"))
        self.assertEqual(legacy.PROXIES["http"], "old-proxy")
        self.assertNotIn("new-token", repr(loaded))

    def test_missing_credentials_get_a_configuration_error(self):
        with self.assertRaises(settings.ConfigurationError) as error:
            settings.Settings().validate()
        self.assertIn("SKYPIXEL_BOT_TOKEN", str(error.exception))
        self.assertIn("SKYPIXEL_MONGODB_URI", str(error.exception))

    def test_missing_secrets_module_allows_environment_only_setup(self):
        with (
            patch.dict(
                os.environ,
                {"SKYPIXEL_BOT_TOKEN": "token", "SKYPIXEL_MONGODB_URI": "uri"},
                clear=True,
            ),
            patch.object(
                settings, "import_module", side_effect=ModuleNotFoundError(name="scrts")
            ),
        ):
            loaded = settings.Settings.load()
        loaded.validate()

    def test_an_error_inside_the_secrets_module_is_not_hidden(self):
        with patch.object(
            settings,
            "import_module",
            side_effect=ModuleNotFoundError(name="missing-helper"),
        ):
            with self.assertRaises(ModuleNotFoundError):
                settings.Settings.load()


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_bot_registers_all_existing_cogs_and_commands(self):
        with patch.object(app.http, "close", new_callable=AsyncMock):
            bot = app.create_bot(command_sync_flags=commands.CommandSyncFlags.none())
            try:
                self.assertEqual(len(bot.cogs), 13)
                self.assertEqual(
                    {
                        command.body.name
                        for command in bot.application_commands_iterator()
                    },
                    {"itemdb", "ranks", "Execute"},
                )
                self.assertTrue(bot.intents.members)
                self.assertIs(constants.BOT, bot)
                for cog in bot.cogs.values():
                    if hasattr(cog, "poll"):
                        self.assertIn(
                            "on_ready", [event for event, _ in cog.get_listeners()]
                        )
            finally:
                await bot.close()
            self.assertIsNone(constants.BOT)

    async def test_one_failed_cog_close_does_not_skip_other_resources(self):
        bot = app.SkypixelBot(command_sync_flags=commands.CommandSyncFlags.none())
        good_close = AsyncMock()

        class FailedCog(commands.Cog):
            async def close(self):
                raise ValueError("close failed")

        class GoodCog(commands.Cog):
            async def close(self):
                await good_close()

        bot.add_cog(FailedCog())
        bot.add_cog(GoodCog())
        with (
            patch.object(app.http, "close", new_callable=AsyncMock) as close_http,
            self.assertLogs(app.logger, level="ERROR"),
        ):
            await bot.close()
            await bot.close()
        good_close.assert_awaited_once()
        close_http.assert_awaited_once()
        self.assertTrue(bot.is_closed())

    async def test_startup_loads_items_before_registering_commands(self):
        events = []
        bot = Mock(close=AsyncMock(), start=AsyncMock())

        async def load_items():
            events.append("items")

        def create_bot():
            events.append("commands")
            return bot

        with (
            patch.object(
                app,
                "settings",
                Mock(
                    bot_token="token",
                    mongodb_uri="uri",
                    proxies={},
                    storage_dir=Path(support.TEST_STORAGE.name),
                ),
            ),
            patch.object(app, "configure_logging"),
            patch.object(hypixel, "load_items", side_effect=load_items),
            patch.object(app, "create_bot", side_effect=create_bot),
        ):
            await app.run()
        self.assertEqual(events, ["items", "commands"])
        bot.start.assert_awaited_once_with("token")
        bot.close.assert_awaited_once()

    async def test_startup_failure_closes_the_http_session(self):
        with (
            patch.object(
                app,
                "settings",
                Mock(
                    bot_token="token",
                    mongodb_uri="uri",
                    proxies={},
                    storage_dir=Path(support.TEST_STORAGE.name),
                ),
            ),
            patch.object(app, "configure_logging"),
            patch.object(
                hypixel,
                "load_items",
                new_callable=AsyncMock,
                side_effect=ValueError("bad catalog"),
            ),
            patch.object(app.http, "close", new_callable=AsyncMock) as close,
            patch.object(constants, "BOT", None),
        ):
            with self.assertRaises(ValueError):
                await app.run()
        close.assert_awaited_once()

    async def test_guild_installed_commands_do_not_need_a_patron_check(self):
        inter = SimpleNamespace(
            authorizing_integration_owners=SimpleNamespace(user_id=None)
        )
        bot = Mock()
        self.assertTrue(await checks.patron_only_check(bot, inter))
        bot.get_guild.assert_not_called()

    async def test_user_installed_commands_keep_the_patron_role_check(self):
        member = Mock(get_role=Mock(return_value=None))
        bot = Mock(
            get_guild=Mock(return_value=Mock(get_member=Mock(return_value=member)))
        )
        inter = SimpleNamespace(
            authorizing_integration_owners=SimpleNamespace(user_id=1),
            author=SimpleNamespace(id=1),
        )
        with self.assertRaises(checks.UserNotAPatron):
            await checks.patron_only_check(bot, inter)


class ImportTests(unittest.TestCase):
    def test_original_import_paths_share_the_new_module_state(self):
        import constants as legacy_constants
        from cogs import itemdb
        from modules import asyncreqs
        from skypixel.clients import http
        from skypixel.commands import itemdb as new_itemdb

        self.assertIs(legacy_constants, constants)
        self.assertIs(asyncreqs, http)
        self.assertIs(itemdb, new_itemdb)

    def test_imports_do_not_open_clients_or_start_the_bot(self):
        source = """import importlib
import pkgutil
import sys
import types
from unittest.mock import patch
secrets = types.ModuleType("scrts")
sys.modules["scrts"] = secrets
with patch("curl_cffi.AsyncSession", side_effect=AssertionError("HTTP session opened")), patch("motor.motor_asyncio.AsyncIOMotorClient", side_effect=AssertionError("MongoDB client opened")):
    import main
    import skypixel
    for module in pkgutil.walk_packages(skypixel.__path__, "skypixel."):
        importlib.import_module(module.name)
    import constants
    assert constants.BOT is None
"""
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "SKYPIXEL_STORAGE_DIR": directory,
            }
            result = subprocess.run(
                [sys.executable, "-c", source],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])
