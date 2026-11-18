import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from pymongo.errors import BulkWriteError

from skypixel.storage import json_store as storage
from skypixel.storage.json_store import StorageError
from skypixel.storage.mongo import Collection, UploadQueue


class JsonFileTests(unittest.IsolatedAsyncioTestCase):
    """The item catalog cache is still a JSON file."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "items.json"

    async def test_save_and_reload(self):
        await storage.write_json(self.path, {"value": 1})
        self.assertEqual(storage.read_json(self.path), {"value": 1})
        self.assertEqual(storage.read_json(self.path.with_name("missing.json")), {})

    async def test_save_keeps_the_existing_file_mode(self):
        self.path.write_text("{}")
        self.path.chmod(0o640)
        await storage.write_json(self.path, {"value": 1})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    async def test_failed_replace_preserves_original_file(self):
        self.path.write_text('{"old": 1}')
        with patch(
            "skypixel.storage.json_store.os.replace",
            side_effect=OSError("disk failure"),
        ):
            with self.assertRaises(OSError):
                await storage.write_json(self.path, {"new": 2})
        self.assertEqual(json.loads(self.path.read_text()), {"old": 1})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    async def test_cancelled_write_finishes_before_the_caller_sees_the_cancel(self):
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = storage._write_atomic

        def write(path, content):
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=2):
                raise TimeoutError("The test did not release the write.")
            original(path, content)

        with patch.object(storage, "_write_atomic", side_effect=write):
            task = asyncio.create_task(storage.write_json(self.path, {"value": 1}))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(storage.read_json(self.path), {"value": 1})

    async def test_corrupt_file_is_not_silently_discarded(self):
        self.path.write_text('{"unfinished":')
        with self.assertRaises(StorageError):
            storage.read_json(self.path)
        self.assertEqual(self.path.read_text(), '{"unfinished":')

    async def test_non_object_file_is_rejected(self):
        self.path.write_text("[]")
        with self.assertRaises(StorageError):
            storage.read_json(self.path)

    async def test_file_without_directory_component(self):
        with patch("skypixel.storage.json_store._write_atomic") as write:
            await storage.write_json("missing-test-state.json", {"value": 1})
        write.assert_called_once()


class MongoStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_batch_does_not_open_a_client(self):
        collection = Collection("mongodb://localhost", "test", "items")
        with patch("skypixel.storage.mongo.AsyncMongoClient") as factory:
            self.assertIsNone(await collection.update_many([]))
            factory.assert_not_called()

    async def test_upsert_keeps_id_out_of_set(self):
        collection = Collection("mongodb://localhost", "test", "items")
        with patch.object(collection, "bulk_write", new_callable=AsyncMock) as write:
            await collection.update_many([{"_id": "item", "value": 1}])
            operation = write.call_args.args[0][0]
        self.assertEqual(operation._filter, {"_id": "item"})
        self.assertEqual(operation._doc, {"$set": {"value": 1}})
        self.assertTrue(operation._upsert)

    async def test_close_is_idempotent(self):
        client = Mock(close=AsyncMock())
        with patch("skypixel.storage.mongo.AsyncMongoClient", return_value=client):
            collection = Collection("mongodb://localhost", "test", "items")
            _ = collection.client
            await collection.close()
            await collection.close()
        client.close.assert_awaited_once()
        with self.assertRaises(RuntimeError):
            _ = collection.client

    async def test_reads_stop_after_the_time_limit(self):
        collection = Collection("mongodb://localhost", "test", "items")
        inner = Mock(count_documents=AsyncMock(), find=Mock())
        with patch.object(Collection, "collection", inner):
            collection.find({})
            await collection.count_documents({})
        self.assertEqual(inner.find.call_args.kwargs["max_time_ms"], 30_000)
        self.assertEqual(inner.count_documents.await_args.kwargs["maxTimeMS"], 30_000)

    async def test_collections_share_one_client_until_the_last_one_closes(self):
        client = Mock(close=AsyncMock())
        with patch(
            "skypixel.storage.mongo.AsyncMongoClient", return_value=client
        ) as factory:
            first = Collection("mongodb://localhost", "test", "one")
            second = Collection("mongodb://localhost", "test", "two")
            self.assertIs(first.client, second.client)
            factory.assert_called_once()
            await first.close()
            client.close.assert_not_awaited()
            await second.close()
        client.close.assert_awaited_once()


class UploadQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_flushes_do_not_remove_new_records(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        queue.append({"_id": "first"})
        started, release = asyncio.Event(), asyncio.Event()
        uploaded = []

        async def update(docs):
            if docs[0]["_id"] == "first":
                started.set()
                await release.wait()
            uploaded.extend(docs)

        with patch.object(queue.collection, "update_many", side_effect=update):
            first = asyncio.create_task(queue.flush())
            await asyncio.wait_for(started.wait(), timeout=1)
            second = asyncio.create_task(queue.flush())
            await asyncio.sleep(0)
            queue.append({"_id": "second"})
            release.set()
            await asyncio.gather(first, second)
        self.assertEqual(uploaded, [{"_id": "first"}, {"_id": "second"}])
        self.assertEqual(queue.docs, [])

    async def test_close_uploads_pending_records_before_closing_the_client(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        queue.append({"_id": "pending"})
        events = []

        async def update(docs):
            events.append(docs)

        async def close():
            events.append("closed")

        with (
            patch.object(queue.collection, "update_many", side_effect=update),
            patch.object(queue.collection, "close", side_effect=close),
        ):
            await queue.close()
            await queue.close()
        self.assertEqual(events, [[{"_id": "pending"}], "closed"])
        with self.assertRaises(RuntimeError):
            queue.append({"_id": "late"})

    async def test_failed_close_keeps_records_and_closes_the_client(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        queue.append({"_id": "pending"})
        with (
            patch.object(queue.collection, "update_many", side_effect=OSError),
            patch.object(queue.collection, "close", new_callable=AsyncMock) as close,
        ):
            with self.assertRaises(OSError):
                await queue.close()
        close.assert_awaited_once()
        self.assertEqual(queue.docs, [{"_id": "pending"}])

    async def test_flush_sends_queued_documents_in_batches_of_1000(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        for index in range(1500):
            queue.append({"_id": index})
        with patch.object(
            queue.collection, "update_many", new_callable=AsyncMock
        ) as write:
            await queue.flush()
        self.assertEqual(
            [len(call.args[0]) for call in write.await_args_list], [1000, 500]
        )
        self.assertEqual(queue.docs, [])

    async def test_empty_flush_does_not_open_a_client(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        with patch("skypixel.storage.mongo.AsyncMongoClient") as factory:
            await queue.flush()
            await queue.close()
        factory.assert_not_called()

    async def test_rejected_documents_do_not_block_the_queue(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        for index in range(3):
            queue.append({"_id": index})
        error = BulkWriteError(
            {"writeErrors": [{"index": 1, "code": 2, "errmsg": "bad document"}]}
        )
        with (
            patch.object(queue.collection, "update_many", side_effect=error),
            self.assertLogs("skypixel.storage.mongo", level="ERROR") as logs,
        ):
            await queue.flush()
        self.assertEqual(queue.docs, [])
        self.assertIn("[1]", logs.output[0])

    async def test_write_concern_errors_keep_the_batch_for_retry(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        queue.append({"_id": "pending"})
        error = BulkWriteError({"writeErrors": [], "writeConcernErrors": [{}]})
        with patch.object(queue.collection, "update_many", side_effect=error):
            with self.assertRaises(BulkWriteError):
                await queue.flush()
        self.assertEqual(queue.docs, [{"_id": "pending"}])

    async def test_full_queue_drops_new_documents(self):
        queue = UploadQueue("mongodb://localhost", "test", "items")
        queue.max_docs = 2
        with self.assertLogs("skypixel.storage.mongo", level="WARNING"):
            for index in range(4):
                queue.append({"_id": index})
        self.assertEqual(queue.docs, [{"_id": 0}, {"_id": 1}])
        self.assertEqual(queue.dropped, 2)
        with (
            patch.object(queue.collection, "update_many", new_callable=AsyncMock),
            self.assertLogs("skypixel.storage.mongo", level="WARNING"),
        ):
            await queue.flush()
        self.assertEqual(queue.dropped, 0)

    async def test_bulk_writes_are_unordered(self):
        collection = Collection("mongodb://localhost", "test", "items")
        with patch.object(collection, "bulk_write", new_callable=AsyncMock) as write:
            await collection.update_many([{"_id": "item"}])
        self.assertFalse(write.call_args.kwargs["ordered"])
