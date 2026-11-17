import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import tests.support as support
from skypixel.clients import http, hypixel, mojang


def response(status=200, data=None):
    return Mock(
        status_code=status,
        url="https://example.com/resource?key=secret",
        json=Mock(return_value=data),
    )


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_attempt_count_does_not_open_a_session(self):
        with patch.object(http, "get_session", new_callable=AsyncMock) as session:
            with self.assertRaises(ValueError):
                await http.get("https://example.com/resource", attempts=0)
        session.assert_not_awaited()

    async def test_get_retries_transient_statuses(self):
        session = Mock(
            request=AsyncMock(side_effect=[response(503), response(429), response(200)])
        )
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
            patch.object(http.asyncio, "sleep", new_callable=AsyncMock),
        ):
            result = await http.get("https://example.com/resource")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(session.request.await_count, 3)

    async def test_retry_waits_for_the_retry_after_header(self):
        limited = response(429)
        limited.headers = {"Retry-After": "12"}
        flooded = response(429)
        flooded.headers = {"Retry-After": "600"}
        session = Mock(request=AsyncMock(side_effect=[limited, flooded, response()]))
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
            patch.object(http.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            await http.get("https://example.com/resource")
        self.assertEqual(
            [call.args[0] for call in sleep.await_args_list],
            [12, http.MAX_RETRY_AFTER],
        )

    async def test_zero_retry_after_keeps_the_retry_delay(self):
        limited = response(429)
        limited.headers = {"Retry-After": "0"}
        session = Mock(request=AsyncMock(side_effect=[limited, limited, response()]))
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
            patch.object(http.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            await http.get("https://example.com/resource")
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [1, 2])

    async def test_retry_warning_names_the_url_and_the_error(self):
        error = http.RequestException("timed out")
        session = Mock(request=AsyncMock(side_effect=[error, response()]))
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
            patch.object(http.asyncio, "sleep", new_callable=AsyncMock),
            self.assertLogs(http.logger, level="WARNING") as logs,
        ):
            await http.get("https://example.com/resource?key=secret")
        self.assertIn("https://example.com/resource", logs.output[0])
        self.assertIn("timed out", logs.output[0])
        self.assertNotIn("secret", logs.output[0])

    async def test_get_retry_count_is_bounded(self):
        session = Mock(request=AsyncMock(return_value=response(503)))
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
            patch.object(http.asyncio, "sleep", new_callable=AsyncMock),
        ):
            result = await http.get("https://example.com/resource")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(session.request.await_count, 3)

    async def test_post_does_not_retry(self):
        session = Mock(request=AsyncMock(return_value=response(503)))
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
        ):
            await http.post("https://example.com/resource", json={"value": 1})
        session.request.assert_awaited_once()

    async def test_not_found_response_reaches_the_caller(self):
        session = Mock(request=AsyncMock(return_value=response(404)))
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
        ):
            result = await http.get("https://example.com/missing")
        self.assertEqual(result.status_code, 404)
        session.request.assert_awaited_once()

    async def test_request_cancellation_propagates(self):
        session = Mock(request=AsyncMock(side_effect=asyncio.CancelledError))
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await http.get("https://example.com/resource")
        session.request.assert_awaited_once()

    async def test_close_is_idempotent(self):
        session = Mock(close=AsyncMock())
        with (
            patch.object(http, "SESSION", session),
            patch.object(http, "CLOSED", False),
        ):
            await http.close()
            await http.close()
            self.assertIsNone(http.SESSION)
            with self.assertRaises(RuntimeError):
                await http.get_session()
        session.close.assert_awaited_once()

    def test_log_urls_hide_credentials_and_queries(self):
        self.assertEqual(
            http.safe_url("https://user:password@example.com/path?api_key=secret"),
            "https://example.com/path",
        )


class HypixelTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_cache_write_keeps_the_loaded_items(self):
        with (
            patch.object(
                hypixel.http,
                "get_json",
                new_callable=AsyncMock,
                return_value={"items": support.ITEMS},
            ),
            patch.object(hypixel, "write_json", side_effect=OSError),
            self.assertLogs(hypixel.logger, level="ERROR"),
        ):
            await hypixel.load_items(support.SETTINGS.storage_dir)
        self.assertEqual(hypixel.ITEMS, support.ITEMS)


class MojangTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mojang.Cache.CACHE.clear()
        self.addCleanup(mojang.Cache.CACHE.clear)

    async def test_cache_normalizes_names_and_uuids(self):
        player = mojang.MojangPlayer("Player", "a" * 32)
        self.assertIs(await mojang.get("PLAYER"), player)
        self.assertIs(await mojang.get("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), player)

    async def test_cache_removes_the_previous_name_after_a_rename(self):
        mojang.MojangPlayer("Before", "a" * 32)
        current = mojang.MojangPlayer("After", "a" * 32)
        self.assertIsNone(mojang.Cache.get("Before"))
        self.assertIs(mojang.Cache.get("After"), current)
        self.assertIs(mojang.Cache.get("a" * 32), current)

    async def test_cache_evicts_old_entries_at_its_size_limit(self):
        with patch.object(mojang.Cache, "MAX_ENTRIES", 4):
            for index in range(3):
                mojang.MojangPlayer(f"Player{index}", f"{index:032x}")
        self.assertLessEqual(len(mojang.Cache.CACHE), 4)
        self.assertIsNone(mojang.Cache.get("Player0"))
        self.assertEqual(mojang.Cache.get("Player2").name, "Player2")

    async def test_cached_lookup_does_not_scan_other_players(self):
        player = mojang.MojangPlayer("Player", "a" * 32)
        with patch.object(mojang.Cache, "cleanup") as cleanup:
            self.assertIs(await mojang.get("Player"), player)
        cleanup.assert_not_called()

    async def test_concurrent_requests_share_the_fetch(self):
        with patch.object(
            mojang.http,
            "get",
            new_callable=AsyncMock,
            return_value=response(data={"id": "a" * 32, "name": "Player"}),
        ) as fetch:
            players = await asyncio.gather(mojang.get("Player"), mojang.get("PLAYER"))
        self.assertIs(players[0], players[1])
        fetch.assert_awaited_once()

    async def test_cancelling_one_caller_keeps_the_fetch_for_another_caller(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def fetch_player(url):
            started.set()
            await release.wait()
            return response(data={"id": "a" * 32, "name": "Player"})

        with patch.object(mojang.http, "get", side_effect=fetch_player) as fetch:
            first = asyncio.create_task(mojang.get("Player"))
            await asyncio.wait_for(started.wait(), timeout=1)
            second = asyncio.create_task(mojang.get("PLAYER"))
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            release.set()
            self.assertEqual((await second).name, "Player")
        fetch.assert_awaited_once()

    async def test_close_waits_for_a_fetch_after_its_caller_is_cancelled(self):
        started, stopped = asyncio.Event(), asyncio.Event()

        async def fetch_player(url):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        with patch.object(mojang.http, "get", side_effect=fetch_player):
            caller = asyncio.create_task(mojang.get("Player"))
            await asyncio.wait_for(started.wait(), timeout=1)
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            await mojang.close()
            await mojang.close()
        self.assertTrue(stopped.is_set())
        self.assertEqual(mojang._inflight, {})

    async def test_old_api_timestamp_does_not_expire_the_cache(self):
        player = mojang.MojangPlayer(
            "Player", "a" * 32, datetime.now(UTC) - timedelta(days=30)
        )
        with patch.object(mojang.http, "get", new_callable=AsyncMock) as fetch:
            self.assertIs(await mojang.get("Player"), player)
        fetch.assert_not_awaited()

    async def test_expired_cache_fetches_again(self):
        player = mojang.MojangPlayer("Player", "a" * 32)
        player.cached_at -= mojang.Cache.TTL.total_seconds()
        with patch.object(
            mojang.http,
            "get",
            new_callable=AsyncMock,
            return_value=response(data={"id": "a" * 32, "name": "Player"}),
        ) as fetch:
            await mojang.get("Player")
        fetch.assert_awaited_once()

    async def test_missing_player_keeps_the_public_exception(self):
        with patch.object(
            mojang.http, "get", new_callable=AsyncMock, return_value=response(404)
        ):
            with self.assertRaises(mojang.PlayerNotFound):
                await mojang.get("missing")

    async def test_bulk_uses_both_uuid_and_name_keys(self):
        with patch.object(
            mojang.http,
            "post",
            new_callable=AsyncMock,
            return_value=response(
                data={"players": [{"id": "a" * 32, "name": "Player"}]}
            ),
        ) as fetch:
            players = await mojang.bulk(["a" * 32, "PLAYER", "PLAYER"])
        self.assertEqual(set(players), {"a" * 32, "player"})
        fetch.assert_awaited_once()

    async def test_empty_bulk_does_not_fetch(self):
        with patch.object(mojang.http, "post", new_callable=AsyncMock) as fetch:
            self.assertEqual(await mojang.bulk([]), {})
        fetch.assert_not_awaited()

    async def test_invalid_identifiers_never_reach_the_api(self):
        with patch.object(mojang.http, "get", new_callable=AsyncMock) as fetch:
            for identifier in ("../ranks/counts", "a?b", "a" * 17, ""):
                with self.assertRaises(mojang.PlayerNotFound):
                    await mojang.get(identifier)
        fetch.assert_not_awaited()
        self.assertTrue(mojang.is_valid_identifier("Some_Player1"))
        self.assertTrue(
            mojang.is_valid_identifier("AAAAAAAA-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        )


class PlayerApiFaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreadable_answer_is_not_reported_as_a_missing_player(self):
        mojang.Cache.CACHE.clear()
        with patch.object(
            mojang.http,
            "get",
            new_callable=AsyncMock,
            return_value=response(data={"error": "down"}),
        ):
            with self.assertRaises(mojang.PlayerLookupError):
                await mojang.get("Player")
