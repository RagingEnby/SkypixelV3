import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from skypixel.clients import http, mojang


def response(status=200, data=None):
    return Mock(
        status_code=status,
        url="https://example.com/resource?key=secret",
        json=Mock(return_value=data),
    )


class HttpTests(unittest.IsolatedAsyncioTestCase):
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


class MojangTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mojang.Cache.CACHE.clear()
        self.addCleanup(mojang.Cache.CACHE.clear)

    async def test_cache_normalizes_names_and_uuids(self):
        player = mojang.MojangPlayer("Player", "a" * 32)
        self.assertIs(await mojang.get("PLAYER"), player)
        self.assertIs(await mojang.get("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), player)

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

    async def test_expired_cache_fetches_again(self):
        mojang.MojangPlayer("Player", "a" * 32, datetime.now(UTC) - timedelta(hours=1))
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
