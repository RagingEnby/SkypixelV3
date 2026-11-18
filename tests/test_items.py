# pyright: reportPrivateUsage=false
import asyncio
import re
import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import disnake

import tests.support as support
from skypixel.commands.item_views import SoulSearchView, make_item_embed
from skypixel.commands.itemdb import ItemDBCog
from skypixel.commands.rank_views import RankListView
from skypixel.commands.views import OwnedView
from skypixel.domain.items import fix_item, make_player_regex, make_playername_regex
from skypixel.domain.types import Document, PrefixRank
from skypixel.storage.items import ItemRepository, soul_rank_pipeline

# The tests pass small fakes where the code expects Discord interactions.
type Inter = disnake.Interaction[disnake.Client]
type MessageInter = disnake.MessageInteraction[disnake.Client]


def field_value(embed: disnake.Embed, index: int) -> str:
    """Return the text of one embed field, which must be set."""
    value = embed.fields[index].value
    assert value is not None
    return value


class ItemTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_soul_removed_during_search_keeps_the_summary(self) -> None:
        cog = ItemDBCog(support.make_bot())
        inter = Mock(send=AsyncMock())
        with (
            patch.object(cog.item_db, "search_souls", return_value={"NON": 1}),
            patch.object(cog.item_db, "find_one", return_value=None),
        ):
            await cog.soul_search_cmd.callback(cog, inter)
        self.assertEqual(len(inter.send.call_args.kwargs["embeds"]), 1)

    async def test_lore_reply_is_deferred_and_fits_discord_limits(self) -> None:
        cog = ItemDBCog(support.make_bot())
        inter = SimpleNamespace(
            component=SimpleNamespace(custom_id="view_lore|item"),
            response=SimpleNamespace(defer=AsyncMock()),
            send=AsyncMock(),
        )
        with patch.object(
            cog.item_db,
            "get_item",
            return_value={"itemId": "ITEM", "lore": ["x" * 5000]},
        ):
            await cog.on_button_click(cast(MessageInter, inter))
        inter.response.defer.assert_awaited_once_with(ephemeral=True, with_message=True)
        self.assertLessEqual(
            len(inter.send.call_args.kwargs["embed"].description), 4096
        )
        self.assertTrue(inter.send.call_args.kwargs["ephemeral"])

    async def test_old_fields_are_repaired_without_changing_the_cached_item(
        self,
    ) -> None:
        raw: Document = {
            "previousOwners": {},
            "lastChecked": {},
            "start": {},
            "createdAt": 1700000000,
        }
        fixed = fix_item(raw)
        self.assertEqual(
            fixed,
            {
                "previousOwners": [],
                "lastChecked": 0,
                "start": 0,
                "created_at": 1700000000000,
            },
        )
        self.assertIsInstance(raw["previousOwners"], dict)
        self.assertEqual(raw["createdAt"], 1700000000)

    async def test_rank_and_name_filters_apply_together(self) -> None:
        cases: tuple[tuple[PrefixRank | None, str, bool], ...] = (
            ("[ADMIN]", "§c[ADMIN] Player§f", True),
            ("[ADMIN]", "§b[MVP§c+§b] Player", False),
            ("[ADMIN]", "§c[ADMIN] Other", False),
            ("[MVP+]", "§b[MVP§c+§b] player", True),
            ("NON", "§7Player", True),
            ("NON", "§a[VIP] Player", False),
        )
        for rank, text, expected in cases:
            with self.subTest(rank=rank, text=text):
                pattern = make_player_regex(rank, "Player")["$regex"]
                assert isinstance(pattern, str)
                self.assertEqual(
                    bool(re.search(pattern, text, re.IGNORECASE)), expected
                )
        self.assertEqual(
            make_player_regex(None, "Player"), make_playername_regex("Player")
        )

    async def test_non_object_query_gets_an_error_without_a_database_call(self) -> None:
        cog = ItemDBCog(support.make_bot())
        inter = support.make_inter()
        with patch.object(cog.item_db, "search", new_callable=AsyncMock) as search:
            await cog.do_search_command(inter, [])
        search.assert_not_awaited()
        self.assertEqual(support.error_title(inter), "Invalid Query")

    async def test_raw_search_rejects_users_other_than_the_owner(self) -> None:
        cog = ItemDBCog(support.make_bot(is_owner=AsyncMock(return_value=False)))
        inter = support.make_inter()
        with patch.object(cog.item_db, "search", new_callable=AsyncMock) as search:
            await cog.search.callback(cog, inter, '{"$where": "sleep(1000)"}')
        search.assert_not_awaited()
        self.assertEqual(support.error_title(inter), "Not Owner")

    async def test_item_cache_has_a_size_limit_and_expires(self) -> None:
        repository = ItemRepository(support.SETTINGS.mongodb_uri)
        repository.cache_limit = 2
        repository.cache_items([{"_id": "a"}, {"_id": "b"}, {"_id": "c"}])
        self.assertEqual(set(repository.cache), {"b", "c"})
        with patch.object(
            repository,
            "find_one",
            new_callable=AsyncMock,
            return_value={"_id": "b", "fresh": True},
        ) as fetch:
            self.assertEqual(await repository.get_item("b"), {"_id": "b"})
            fetch.assert_not_awaited()
            repository._cached_at["b"] -= repository.cache_ttl
            fresh = await repository.get_item("b")
            assert fresh is not None
            self.assertTrue(fresh["fresh"])
        fetch.assert_awaited_once()

    async def test_soul_pipeline_keeps_the_query_and_rank_grouping(self) -> None:
        query = {"itemId": "CAKE_SOUL"}
        pipeline = soul_rank_pipeline(query)
        self.assertEqual(pipeline[0], {"$match": query})
        self.assertEqual(
            pipeline[3], {"$group": {"_id": "$captured_rank", "count": {"$sum": 1}}}
        )

    async def test_item_embed_keeps_the_owner_and_timestamps(self) -> None:
        item: Document = {
            "_id": "item",
            "coflUid": "cofl",
            "itemId": "TEST_MEMENTO",
            "friendlyName": "§cMemento",
            "rarity": "SPECIAL",
            "previousOwners": [],
            "currentOwner": {"playerUuid": "player"},
            "start": 1700000000000,
            "lastChecked": 1700000000000,
            "extraAttributes": {},
        }
        with patch(
            "skypixel.commands.item_views.mojang.bulk",
            new_callable=AsyncMock,
            return_value={},
        ):
            embed = await make_item_embed(item)
        self.assertEqual(embed.title, "Memento")
        self.assertEqual(embed.author.name, "player")
        self.assertEqual(embed.fields[0].value, "item\n-# **Cofl UID:** cofl")
        self.assertIn("<t:1700000000:d>", field_value(embed, 1))

    async def test_failed_owner_lookup_still_builds_the_item_embed(self) -> None:
        item: Document = {
            "_id": "item",
            "coflUid": "cofl",
            "itemId": "TEST_MEMENTO",
            "previousOwners": [],
            "currentOwner": {"playerUuid": "player"},
            "start": 1700000000000,
            "lastChecked": 1700000000000,
        }
        with (
            patch(
                "skypixel.commands.item_views.mojang.bulk",
                new_callable=AsyncMock,
                side_effect=RuntimeError("player api down"),
            ),
            self.assertLogs("skypixel.commands.item_views", level="ERROR"),
        ):
            embed = await make_item_embed(item)
        self.assertEqual(embed.author.name, "player")

    async def test_missing_item_fields_show_as_unknown(self) -> None:
        item: Document = {
            "_id": "item",
            "itemId": "TEST_MEMENTO",
            "previousOwners": [{"owner": {"playerUuid": "old"}}],
            "currentOwner": {"playerUuid": "player"},
            "lastChecked": {},
        }
        with patch(
            "skypixel.commands.item_views.mojang.bulk",
            new_callable=AsyncMock,
            return_value={},
        ):
            embed = await make_item_embed(item)
        self.assertIn("Cofl UID:** unknown", field_value(embed, 0))
        self.assertIn("since unknown", field_value(embed, 1))
        self.assertIn("last seen unknown", field_value(embed, 1))
        self.assertEqual(embed.fields[2].value, "old (unknown - unknown)")


class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_soul_buttons_defer_and_serialize_concurrent_page_loads(self) -> None:
        inter = SimpleNamespace(user="owner")
        cursor = Mock(next=AsyncMock())
        cursor.sort.return_value = cursor
        repository = Mock(find=Mock(return_value=cursor))
        view = SoulSearchView(
            {}, 3, disnake.Embed(title="Summary"), repository, cast(Inter, inter)
        )
        self.addCleanup(view.stop)
        started, release = asyncio.Event(), asyncio.Event()

        async def item() -> Document:
            return {"_id": str(cursor.skip.call_args.args[0])}

        async def embed(data: Document) -> disnake.Embed:
            if data["_id"] == "1":
                started.set()
                await release.wait()
            return disnake.Embed(title=data["_id"])

        def interaction() -> SimpleNamespace:
            return SimpleNamespace(
                response=SimpleNamespace(defer=AsyncMock()),
                edit_original_message=AsyncMock(),
            )

        cursor.next.side_effect = item
        first_inter, second_inter = interaction(), interaction()
        with patch("skypixel.commands.item_views.make_item_embed", side_effect=embed):
            first = asyncio.create_task(
                view.next.callback(cast(MessageInter, first_inter))
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            second = asyncio.create_task(
                view.next.callback(cast(MessageInter, second_inter))
            )
            await asyncio.sleep(0)
            second_inter.response.defer.assert_awaited_once()
            self.assertEqual(view.index, 1)
            release.set()
            await asyncio.gather(first, second)
        self.assertEqual(view.embed_cache[1].title, "1")
        self.assertEqual(view.embed_cache[2].title, "2")
        self.assertTrue(view.next.disabled)

    async def test_removed_soul_disables_the_end_of_the_result_list(self) -> None:
        cursor = Mock(next=AsyncMock(side_effect=StopAsyncIteration))
        cursor.sort.return_value = cursor
        view = SoulSearchView(
            {}, 2, disnake.Embed(), Mock(find=Mock(return_value=cursor)), Mock()
        )
        self.addCleanup(view.stop)
        view.index = 1
        self.assertIsNone(await view.get_current_embed())
        self.assertEqual((view.index, view.count), (0, 1))
        self.assertTrue(view.next.disabled)
        self.assertTrue(view.previous.disabled)

    async def test_soul_page_cache_has_a_size_limit(self) -> None:
        cursor = Mock(next=AsyncMock(return_value={"_id": "item"}))
        cursor.sort.return_value = cursor
        view = SoulSearchView(
            {}, 5, disnake.Embed(), Mock(find=Mock(return_value=cursor)), Mock()
        )
        self.addCleanup(view.stop)
        view.cache_limit = 2
        with patch(
            "skypixel.commands.item_views.make_item_embed", return_value=disnake.Embed()
        ):
            for index in range(5):
                view.index = index
                await view.get_current_embed()
        self.assertEqual(set(view.item_cache), {3, 4})
        self.assertEqual(
            cursor.sort.call_args.args[0],
            [("extraAttributes.captured_date", -1), ("_id", 1)],
        )
        self.assertEqual(set(view.embed_cache), {3, 4})

    async def test_another_user_cannot_click_the_view(self) -> None:
        view = OwnedView(cast(Inter, SimpleNamespace(user="owner")))
        inter = SimpleNamespace(
            user="someone", response=SimpleNamespace(send_message=AsyncMock())
        )
        self.assertFalse(await view.interaction_check(cast(MessageInter, inter)))
        self.assertTrue(inter.response.send_message.call_args.kwargs["ephemeral"])
        view.stop()

    async def test_timeout_disables_buttons_and_edits_the_message(self) -> None:
        inter = SimpleNamespace(user="owner", edit_original_message=AsyncMock())
        view = OwnedView(cast(Inter, inter))
        # disnake types add_item with a bare Item, so pyright sees Item[Unknown].
        view.add_item(  # pyright: ignore[reportUnknownMemberType]
            disnake.ui.Button[OwnedView](label="Next")
        )
        await view.on_timeout()
        button = view.children[0]
        assert isinstance(button, disnake.ui.Button)
        self.assertTrue(button.disabled)
        inter.edit_original_message.assert_awaited_once_with(view=view)
        view.stop()

    async def test_rank_buttons_cannot_move_outside_the_page_list(self) -> None:
        inter = SimpleNamespace(
            user="owner", response=SimpleNamespace(edit_message=AsyncMock())
        )
        view = RankListView([disnake.Embed(title="Only page")], cast(Inter, inter))
        await view.previous.callback(cast(MessageInter, inter))
        self.assertEqual(view.page, 0)
        await view.next.callback(cast(MessageInter, inter))
        self.assertEqual(view.page, 0)
        view.stop()
