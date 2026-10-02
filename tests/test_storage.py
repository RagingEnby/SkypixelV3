import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from skypixel.storage import json as storage
from skypixel.storage.json import JsonWrapper, StorageError
from skypixel.storage.mongo import Collection, UploadQueue


class JsonStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"

    async def test_save_and_reload(self):
        state = JsonWrapper(self.path)
        state["player"] = {"rank": "staff", "name": "Player"}
        await state.save()
        self.assertEqual(JsonWrapper(self.path).to_dict(), state.to_dict())

    async def test_mapping_views_follow_loaded_and_replaced_data(self):
        self.path.write_text('{"old": 1}')
        state = JsonWrapper(self.path)
        self.assertEqual(list(state.items()), [("old", 1)])
        state.data = {"new": 2}
        self.assertEqual(list(state.keys()), ["new"])
        self.assertEqual(list(state.values()), [2])

    async def test_failed_replace_preserves_original_file(self):
        self.path.write_text('{"old": 1}')
        state = JsonWrapper(self.path)
        state.data = {"new": 2}
        with patch(
            "skypixel.storage.json.os.replace", side_effect=OSError("disk failure")
        ):
            with self.assertRaises(OSError):
                await state.save()
        self.assertEqual(json.loads(self.path.read_text()), {"old": 1})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    async def test_cancelled_save_waits_for_the_write_before_releasing_the_lock(self):
        state = JsonWrapper(self.path)
        state.data = {"first": 1}
        started = asyncio.Event()
        release, second_started = threading.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        original = storage._write_atomic

        def write(path, content):
            if json.loads(content) == {"first": 1}:
                loop.call_soon_threadsafe(started.set)
                if not release.wait(timeout=2):
                    raise TimeoutError("The test did not release the first write.")
            else:
                second_started.set()
            original(path, content)

        with patch.object(storage, "_write_atomic", side_effect=write):
            first = asyncio.create_task(state.save())
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                first.cancel()
                state.data = {"second": 2}
                second = asyncio.create_task(state.save())
                await asyncio.sleep(0)
                self.assertFalse(first.done())
                self.assertFalse(second_started.is_set())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await first
            await second
        self.assertEqual(json.loads(self.path.read_text()), {"second": 2})

    async def test_corrupt_state_is_not_silently_discarded(self):
        self.path.write_text('{"unfinished":')
        with self.assertRaises(StorageError):
            JsonWrapper(self.path)
        self.assertEqual(self.path.read_text(), '{"unfinished":')

    async def test_non_object_state_is_rejected(self):
        self.path.write_text("[]")
        with self.assertRaises(StorageError):
            JsonWrapper(self.path)

    async def test_file_without_directory_component(self):
        with patch("skypixel.storage.json._write_atomic") as write:
            state = JsonWrapper("missing-test-state.json")
            state["value"] = 1
            await state.save()
        write.assert_called_once()


class MongoStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_batch_does_not_open_a_client(self):
        collection = Collection("test", "items")
        with patch("skypixel.storage.mongo.AsyncIOMotorClient") as factory:
            self.assertIsNone(await collection.update_many([]))
            factory.assert_not_called()

    async def test_upsert_keeps_id_out_of_set(self):
        collection = Collection("test", "items")
        with patch.object(collection, "bulk_write", new_callable=AsyncMock) as write:
            await collection.update_many([{"_id": "item", "value": 1}])
            operation = write.call_args.args[0][0]
        self.assertEqual(operation._filter, {"_id": "item"})
        self.assertEqual(operation._doc, {"$set": {"value": 1}})
        self.assertTrue(operation._upsert)

    async def test_close_is_idempotent(self):
        collection = Collection("test", "items")
        client = Mock()
        collection._client = client
        await collection.close()
        await collection.close()
        client.close.assert_called_once()
        with self.assertRaises(RuntimeError):
            _ = collection.client


class UploadQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_flush_sends_queued_documents_in_batches_of_1000(self):
        queue = UploadQueue("test", "items")
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
        queue = UploadQueue("test", "items")
        with patch("skypixel.storage.mongo.AsyncIOMotorClient") as factory:
            await queue.flush()
            await queue.close()
        factory.assert_not_called()
