import gzip
import io
import unittest
from base64 import b64encode
from unittest.mock import patch

from nbt import nbt
from skypixel.domain import nbt as item_nbt
from skypixel.domain.nbt import ItemDecodeError, decode_single, ensure_all_decoded


class NbtTests(unittest.TestCase):
    def test_non_compound_items_have_a_clear_error(self):
        root = nbt.NBTFile()
        items = nbt.TAG_List(name="i", type=nbt.TAG_Int)
        items.tags.append(nbt.TAG_Int(value=1))
        root.tags.append(items)
        buffer = io.BytesIO()
        root.write_file(buffer=buffer)
        encoded = b64encode(gzip.compress(buffer.getvalue())).decode()
        with self.assertRaises(ItemDecodeError):
            decode_single(encoded)

    def test_invalid_base64_characters_are_rejected(self):
        root = nbt.NBTFile()
        root.tags.append(nbt.TAG_List(name="i", type=nbt.TAG_Compound))
        buffer = io.BytesIO()
        root.write_file(buffer=buffer)
        encoded = b64encode(gzip.compress(buffer.getvalue())).decode()
        with self.assertRaisesRegex(ItemDecodeError, "base64"):
            decode_single("!" + encoded)

    def test_non_text_item_data_has_a_clear_error(self):
        for value in (None, {}, 1):
            with self.subTest(value=value), self.assertRaises(ItemDecodeError):
                decode_single(value)

    def test_fork_reads_modified_utf8_strings(self):
        encoded = b"\x00\x09a\xc0\x80\xed\xa0\xbd\xed\xb8\x80"
        tag = nbt.TAG_String(buffer=io.BytesIO(encoded))
        self.assertEqual(tag.value, "a\x00\U0001f600")

    def test_fork_writes_null_as_modified_utf8(self):
        tag = nbt.TAG_String(value="a\x00")
        buffer = io.BytesIO()
        tag._render_buffer(buffer)
        self.assertEqual(buffer.getvalue(), b"\x00\x03a\xc0\x80")

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
        self.assertEqual(decode_single(encoded), {"petInfo": {"type": "SHEEP"}})

    def test_nested_lists_decode(self):
        self.assertEqual(
            ensure_all_decoded({"nested": [[{"petInfo": '{"type":"SHEEP"}'}]]}),
            {"nested": [[{"petInfo": {"type": "SHEEP"}}]]},
        )

    def test_bad_item_data_has_a_clear_error(self):
        with self.assertRaises(ItemDecodeError):
            decode_single("invalid")

    def test_empty_item_list_has_a_clear_error(self):
        with patch.object(item_nbt, "decode", return_value=[]):
            with self.assertRaises(ItemDecodeError):
                decode_single("")

    def test_corrupt_compressed_data_has_a_clear_error(self):
        data = gzip.compress(b"\x0a\x00\x00\x00" * 64)
        corrupt = data[:10] + bytes(len(data) - 10)
        with self.assertRaises(ItemDecodeError):
            decode_single(b64encode(corrupt).decode())

    def test_byte_arrays_are_stored_as_base64_text(self):
        self.assertEqual(
            ensure_all_decoded({"data": bytearray(b"\x1f\x8b\x00")}), {"data": "H4sA"}
        )
