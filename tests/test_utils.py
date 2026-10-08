import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import disnake
from disnake.ext import commands

import tests.support as support
from skypixel import checks, utils
from skypixel.commands import owner
from skypixel.commands.logger import ATTACHMENT_BUDGET, LoggerCog
from skypixel.logging import RedactingFormatter, configure_logging


class DiscordTests(unittest.IsolatedAsyncioTestCase):
    def test_timestamps_normalize_seconds_and_milliseconds(self):
        for value, expected in (
            (0, 0),
            (946684800, 946684800),
            (1700000000, 1700000000),
            (1700000000000, 1700000000),
            ("1700000000000", 1700000000),
            ("1700000000000L", 1700000000),
        ):
            with self.subTest(value=value):
                self.assertEqual(utils.normalize_timestamp(value), expected)

    async def test_response_uses_the_right_interaction_endpoint(self):
        embed = disnake.Embed(title="Error")
        for done in (False, True):
            inter = SimpleNamespace(
                response=SimpleNamespace(
                    is_done=lambda done=done: done, send_message=AsyncMock()
                ),
                followup=SimpleNamespace(send=AsyncMock()),
            )
            await utils.respond(inter, embed=embed)
            target = inter.followup.send if done else inter.response.send_message
            target.assert_awaited_once_with(embed=embed, ephemeral=True)

    async def test_thread_send_failure_is_logged_and_returns_none(self):
        thread = Mock(spec=disnake.Thread)
        thread.send = AsyncMock(
            side_effect=disnake.Forbidden(
                Mock(status=403, reason="Forbidden"), "No access"
            )
        )
        channel = Mock(spec=disnake.TextChannel, get_thread=Mock(return_value=thread))
        bot = Mock(get_channel=Mock(return_value=channel))
        with self.assertLogs(utils.logger, level="ERROR"):
            self.assertIsNone(
                await utils.send_to_channel(bot, 1, thread_id=2, content="test")
            )

    async def test_broadcast_obeys_the_ten_embed_limit(self):
        embeds = [disnake.Embed(title=str(index)) for index in range(23)]
        with patch.object(utils, "send_to_channel", new_callable=AsyncMock) as send:
            await utils.broadcast(Mock(), {1: "ping"}, embeds=embeds)
        self.assertEqual(
            [len(call.kwargs["embeds"]) for call in send.call_args_list], [10, 10, 3]
        )

    async def test_long_embed_fits_discord_limits(self):
        embed = disnake.Embed(title="t" * 300, description="d" * 5000)
        for _ in range(30):
            embed.add_field(name="n" * 300, value="v" * 2000)
        utils.fit_embed(embed)
        self.assertLessEqual(len(embed), 6000)
        self.assertLessEqual(len(embed.title), 256)
        self.assertLessEqual(len(embed.description), 4096)
        self.assertLessEqual(len(embed.fields), 25)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))

    async def test_broadcast_splits_large_embeds_without_cutting_text(self):
        embeds = [disnake.Embed(description="x" * 4000) for _ in range(3)]
        with patch.object(utils, "send_to_channel", new_callable=AsyncMock) as send:
            await utils.broadcast(Mock(), {1: "ping"}, embeds=embeds)
        self.assertEqual(len(send.call_args_list), 3)
        self.assertEqual(
            [sum(map(len, call.kwargs["embeds"])) for call in send.call_args_list],
            [4000, 4000, 4000],
        )

    async def test_combined_embeds_fit_without_changing_cached_embeds(self):
        embeds = [disnake.Embed(description="x" * 4000) for _ in range(2)]
        embeds[0].add_field(name="Attributes", value="v" * 1000)
        result = utils.fit_embeds(embeds)
        self.assertLessEqual(sum(map(len, result)), 6000)
        self.assertEqual(embeds[0].fields[0].value, "v" * 1000)
        self.assertEqual(embeds[0].description, "x" * 4000)

    async def test_combined_embeds_handle_long_titles_and_footers(self):
        embeds = []
        for _ in range(10):
            embed = disnake.Embed(title="t" * 256)
            embed.set_author(name="a" * 256)
            embed.set_footer(text="f" * 2048)
            embeds.append(embed)
        self.assertLessEqual(sum(map(len, utils.fit_embeds(embeds))), 6000)

    async def test_check_errors_use_a_private_followup(self):
        cog = LoggerCog(support.make_bot())
        inter = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: True),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        await cog.on_slash_command_error(inter, checks.UserNotAPatron("Missing role"))
        self.assertEqual(
            inter.followup.send.call_args.kwargs["embed"].title, "Patron Only"
        )
        self.assertTrue(inter.followup.send.call_args.kwargs["ephemeral"])

    async def test_owner_command_checks_the_owner_before_it_runs_code(self):
        bot = commands.InteractionBot(
            command_sync_flags=commands.CommandSyncFlags.none()
        )
        bot.is_owner = AsyncMock(return_value=False)
        owner.register(bot)
        inter = Mock(send=AsyncMock())
        message = Mock(
            content="```py\nraise RuntimeError('should not run')\n```",
            add_reaction=AsyncMock(),
        )
        await bot.get_message_command("Execute").callback(inter, message)
        self.assertEqual(inter.send.call_args.kwargs["embed"].title, "Not Owner")
        message.add_reaction.assert_not_awaited()
        await bot.close()

    async def test_owner_command_retains_its_execution_context(self):
        bot = commands.InteractionBot(
            command_sync_flags=commands.CommandSyncFlags.none()
        )
        bot.is_owner = AsyncMock(return_value=True)
        owner.register(bot)
        inter = SimpleNamespace(
            author="owner",
            response=SimpleNamespace(defer=AsyncMock()),
            marker=None,
            send=AsyncMock(),
        )
        message = Mock(
            content="```py\ninter.marker = bot.owner_id\n```", add_reaction=AsyncMock()
        )
        bot.owner_id = 42
        await bot.get_message_command("Execute").callback(inter, message)
        self.assertEqual(inter.marker, 42)
        inter.send.assert_not_awaited()
        await bot.close()

    def test_log_formatter_redacts_exception_text(self):
        try:
            raise ValueError("credential=private-token")
        except ValueError as error:
            record = logging.LogRecord(
                "test",
                logging.ERROR,
                "test.py",
                1,
                "Request failed for %s",
                ("private-token",),
                (type(error), error, error.__traceback__),
            )
        result = RedactingFormatter("%(message)s", ("private-token",)).format(record)
        self.assertNotIn("private-token", result)
        self.assertIn("[redacted]", result)


class LoggingTests(unittest.TestCase):
    def test_only_the_bot_logs_debug_messages(self):
        root = logging.getLogger()
        level = root.level
        with tempfile.TemporaryDirectory() as directory:
            try:
                configure_logging(Path(directory))
                self.assertFalse(
                    logging.getLogger("pymongo.command").isEnabledFor(logging.DEBUG)
                )
                self.assertTrue(
                    logging.getLogger("skypixel.trackers").isEnabledFor(logging.DEBUG)
                )
            finally:
                for logger in (root, logging.getLogger("disnake")):
                    for handler in list(logger.handlers):
                        if getattr(handler, "_skypixel_handler", False):
                            logger.removeHandler(handler)
                            handler.close()
                root.setLevel(level)


class DirectMessageLogTests(unittest.IsolatedAsyncioTestCase):
    def attachment(self, size, url):
        return Mock(size=size, url=url, to_file=AsyncMock(return_value=url))

    async def test_large_attachments_are_linked_instead_of_uploaded(self):
        small = self.attachment(1024, "small")
        large = self.attachment(ATTACHMENT_BUDGET, "large")
        message = Mock(
            content="",
            guild=None,
            attachments=[small, large],
            created_at=None,
            author=Mock(
                bot=False, display_name="User", id=1, color=None, display_avatar=None
            ),
        )
        with patch.object(utils, "send_to_channel", new_callable=AsyncMock) as send:
            await LoggerCog(support.make_bot()).on_message(message)
        large.to_file.assert_not_awaited()
        self.assertEqual(send.await_args.kwargs["files"], ["small"])
        self.assertEqual(send.await_args.kwargs["embed"].fields[0].value, "large")
