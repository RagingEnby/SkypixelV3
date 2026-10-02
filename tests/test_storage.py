import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tests import support
from skypixel.storage.json import JsonWrapper, StorageError
from skypixel.storage.mongo import Collection


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
            collection.client
