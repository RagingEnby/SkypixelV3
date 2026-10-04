import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import disnake

from skypixel.commands.item_views import SoulSearchView, make_item_embed
from skypixel.commands.itemdb import ItemDBCog
from skypixel.commands.rank_views import RankListView
from skypixel.commands.views import OwnedView
from skypixel.domain.items import fix_item, make_player_regex, make_playername_regex
from skypixel.storage.items import ItemRepository, soul_rank_pipeline


class ItemTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_soul_removed_during_search_keeps_the_summary(self):
        cog = ItemDBCog(Mock())
        inter = Mock(send=AsyncMock())
        with (
            patch.object(cog.item_db, "search_souls", return_value={"NON": 1}),
            patch.object(cog.item_db, "find_one", return_value=None),
        ):
            await cog.soul_search_cmd.callback(cog, inter)
        self.assertEqual(len(inter.send.call_args.kwargs["embeds"]), 1)

    async def test_lore_reply_is_deferred_and_fits_discord_limits(self):
        cog = ItemDBCog(Mock())
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
            await cog.on_button_click(inter)
        inter.response.defer.assert_awaited_once_with(ephemeral=True, with_message=True)
        self.assertLessEqual(
            len(inter.send.call_args.kwargs["embed"].description), 4096
        )
        self.assertTrue(inter.send.call_args.kwargs["ephemeral"])

    async def test_old_fields_are_repaired_without_changing_the_cached_item(self):
        raw = {
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

    async def test_player_name_filters_keep_the_existing_precedence(self):
        self.assertEqual(
            make_player_regex("[ADMIN]", "Player"), make_playername_regex("Player")
        )

    async def test_non_object_query_gets_an_error_without_a_database_call(self):
        cog = ItemDBCog(Mock())
        inter = Mock(send=AsyncMock())
        with patch.object(cog.item_db, "search", new_callable=AsyncMock) as search:
            await cog.do_search_command(inter, [])
        search.assert_not_awaited()
        self.assertEqual(inter.send.call_args.kwargs["embed"].title, "Invalid Query")

    async def test_raw_search_rejects_users_other_than_the_owner(self):
        cog = ItemDBCog(Mock(is_owner=AsyncMock(return_value=False)))
        inter = Mock(send=AsyncMock())
        with patch.object(cog.item_db, "search", new_callable=AsyncMock) as search:
            await cog.search.callback(cog, inter, '{"$where": "sleep(1000)"}')
        search.assert_not_awaited()
        self.assertEqual(inter.send.call_args.kwargs["embed"].title, "Not Owner")

    async def test_item_cache_has_a_size_limit_and_expires(self):
        repository = ItemRepository()
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
            self.assertTrue((await repository.get_item("b"))["fresh"])
        fetch.assert_awaited_once()

    async def test_soul_pipeline_keeps_the_query_and_rank_grouping(self):
        query = {"itemId": "CAKE_SOUL"}
        pipeline = soul_rank_pipeline(query)
        self.assertEqual(pipeline[0], {"$match": query})
        self.assertEqual(
            pipeline[3], {"$group": {"_id": "$captured_rank", "count": {"$sum": 1}}}
        )

    async def test_item_embed_keeps_the_owner_and_timestamps(self):
        item = {
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
        self.assertIn("<t:1700000000:d>", embed.fields[1].value)


class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_soul_buttons_defer_and_serialize_concurrent_page_loads(self):
        inter = SimpleNamespace(user="owner")
        cursor = Mock(next=AsyncMock())
        cursor.sort.return_value = cursor
        repository = Mock(find=Mock(return_value=cursor))
        view = SoulSearchView({}, 3, disnake.Embed(title="Summary"), repository, inter)
        self.addCleanup(view.stop)
        started, release = asyncio.Event(), asyncio.Event()

        async def item():
            return {"_id": str(cursor.skip.call_args.args[0])}

        async def embed(data):
            if data["_id"] == "1":
                started.set()
                await release.wait()
            return disnake.Embed(title=data["_id"])

        def interaction():
            return SimpleNamespace(
                response=SimpleNamespace(defer=AsyncMock()),
                edit_original_message=AsyncMock(),
            )

        cursor.next.side_effect = item
        first_inter, second_inter = interaction(), interaction()
        with patch("skypixel.commands.item_views.make_item_embed", side_effect=embed):
            first = asyncio.create_task(view.next.callback(first_inter))
            await asyncio.wait_for(started.wait(), timeout=1)
            second = asyncio.create_task(view.next.callback(second_inter))
            await asyncio.sleep(0)
            second_inter.response.defer.assert_awaited_once()
            self.assertEqual(view.index, 1)
            release.set()
            await asyncio.gather(first, second)
        self.assertEqual(view.embed_cache[1].title, "1")
        self.assertEqual(view.embed_cache[2].title, "2")
        self.assertTrue(view.next.disabled)

    async def test_removed_soul_disables_the_end_of_the_result_list(self):
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

    async def test_soul_page_cache_has_a_size_limit(self):
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
        self.assertEqual(set(view.embed_cache), {3, 4})

    async def test_another_user_cannot_click_the_view(self):
        view = OwnedView(SimpleNamespace(user="owner"))
        inter = SimpleNamespace(
            user="someone", response=SimpleNamespace(send_message=AsyncMock())
        )
        self.assertFalse(await view.interaction_check(inter))
        self.assertTrue(inter.response.send_message.call_args.kwargs["ephemeral"])
        view.stop()

    async def test_timeout_disables_buttons_and_edits_the_message(self):
        inter = SimpleNamespace(user="owner", edit_original_message=AsyncMock())
        view = OwnedView(inter)
        view.add_item(disnake.ui.Button(label="Next"))
        await view.on_timeout()
        self.assertTrue(view.children[0].disabled)
        inter.edit_original_message.assert_awaited_once_with(view=view)
        view.stop()

    async def test_rank_buttons_cannot_move_outside_the_page_list(self):
        inter = SimpleNamespace(
            user="owner", response=SimpleNamespace(edit_message=AsyncMock())
        )
        view = RankListView([disnake.Embed(title="Only page")], inter)
        await view.previous.callback(inter)
        self.assertEqual(view.page, 0)
        await view.next.callback(inter)
        self.assertEqual(view.page, 0)
        view.stop()
