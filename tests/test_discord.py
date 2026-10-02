import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import disnake
from disnake.ext import commands

from skypixel import checks
from skypixel import discord as utils
from skypixel.commands import owner
from skypixel.commands.logger import LoggerCog
from skypixel.logging import RedactingFormatter


class DiscordTests(unittest.IsolatedAsyncioTestCase):
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
        with (
            patch.object(
                utils.constants, "BOT", Mock(get_channel=Mock(return_value=channel))
            ),
            self.assertLogs(utils.logger, level="ERROR"),
        ):
            self.assertIsNone(
                await utils.send_to_channel(1, thread_id=2, content="test")
            )

    async def test_broadcast_obeys_the_ten_embed_limit(self):
        embeds = [disnake.Embed(title=str(index)) for index in range(23)]
        with patch.object(utils, "send_to_channel", new_callable=AsyncMock) as send:
            await utils.broadcast({1: "ping"}, embeds=embeds)
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
            await utils.broadcast({1: "ping"}, embeds=embeds)
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
        cog = LoggerCog(Mock())
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
