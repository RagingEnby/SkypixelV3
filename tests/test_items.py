import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import disnake

from skypixel.commands.item_views import make_item_embed
from skypixel.commands.itemdb import ItemDBCog
from skypixel.commands.rank_views import RankListView
from skypixel.commands.views import OwnedView
from skypixel.domain.items import fix_item, make_player_regex, make_playername_regex
from skypixel.storage.items import ItemRepository, soul_rank_pipeline


class ItemTests(unittest.IsolatedAsyncioTestCase):
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
