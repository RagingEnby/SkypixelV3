import io
import gzip
import unittest
from base64 import b64encode

from nbt import nbt

from tests import support
from skypixel.domain import nbt as parser


class NbtTests(unittest.TestCase):
    def test_round_trip_item_and_pet_info(self):
        root = nbt.NBTFile()
        items = nbt.TAG_List(name="i", type=nbt.TAG_Compound)
        item = nbt.TAG_Compound()
        item.tags.append(nbt.TAG_String(name="petInfo", value='{"type": "SHEEP"}'))
        items.tags.append(item)
        root.tags.append(items)
        buffer = io.BytesIO()
        root.write_file(buffer=buffer)
        encoded = b64encode(gzip.compress(buffer.getvalue())).decode()
        self.assertEqual(parser.decode_single(encoded), {"petInfo": {"type": "SHEEP"}})

    def test_nested_lists_decode(self):
        self.assertEqual(
            parser.ensure_all_decoded({"nested": [[{"petInfo": '{"type":"SHEEP"}'}]]}),
            {"nested": [[{"petInfo": {"type": "SHEEP"}}]]},
        )

    def test_bad_item_data_has_a_clear_error(self):
        with self.assertRaises(parser.ItemDecodeError):
            parser.decode_single("invalid")

    def test_empty_item_list_has_a_clear_error(self):
        with support.patch.object(parser, "decode", return_value=[]):
            with self.assertRaises(parser.ItemDecodeError):
                parser.decode_single("")
