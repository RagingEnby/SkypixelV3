import io
import json
import zlib
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from contextlib import suppress
from typing import TypeGuard, overload

from nbt import nbt

# A value read from NBT. Int arrays arrive as list[int] and byte arrays as
# bytearray. ensure_all_decoded also puts parsed petInfo JSON here.
type NBTData = (
    dict[str, NBTData]
    | list[NBTData]
    | list[int]
    | bytearray
    | str
    | int
    | float
    | bool
    | None
)


class ItemDecodeError(ValueError):
    pass


def nbt_to_dict(nbt_data: nbt.TAG) -> NBTData:
    if isinstance(nbt_data, (nbt.NBTFile, nbt.TAG_Compound)):
        return {tag.name: nbt_to_dict(tag) for tag in nbt_data.tags}
    if isinstance(nbt_data, nbt.TAG_List):
        return [nbt_to_dict(item) for item in nbt_data.tags]
    return nbt_data.value


def _is_item_list(items: NBTData) -> TypeGuard[list[dict[str, NBTData]]]:
    return isinstance(items, list) and not any(
        not isinstance(item, dict) for item in items
    )


def raw_decode(data: bytes) -> list[dict[str, NBTData]]:
    try:
        with io.BytesIO(data) as fileobj:
            parsed = nbt_to_dict(nbt.NBTFile(fileobj=fileobj))
    except (
        OSError,
        EOFError,
        ValueError,
        KeyError,
        zlib.error,
        nbt.MalformedFileError,
    ) as error:
        raise ItemDecodeError("Cannot decode the item NBT data.") from error
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"i"}
        or not _is_item_list(items := parsed["i"])
    ):
        raise ItemDecodeError("Expected an NBT item list.")
    return items


@overload
def ensure_all_decoded(data: dict[str, NBTData]) -> dict[str, NBTData]: ...
@overload
def ensure_all_decoded(data: NBTData) -> NBTData: ...
def ensure_all_decoded(data: NBTData) -> NBTData:
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "petInfo" and isinstance(value, str):
                with suppress(json.JSONDecodeError):
                    value = json.loads(value)
            data[key] = ensure_all_decoded(value)
        return data
    if isinstance(data, list):
        return [ensure_all_decoded(item) for item in data]
    if isinstance(data, bytearray):
        # Backpack contents and similar arrive as byte arrays. Store them as
        # base64 text, the same form Hypixel uses for item data.
        return b64encode(data).decode()
    return data


def decode(item_bytes: object) -> list[dict[str, NBTData]]:
    """Decode base64 item data. Anything other than a str raises ItemDecodeError."""
    if not isinstance(item_bytes, str):
        raise ItemDecodeError("Expected base64 item data as text.")
    try:
        raw = b64decode(item_bytes, validate=True)
    except (Base64Error, ValueError) as error:
        raise ItemDecodeError("The item data is not valid base64.") from error
    return [ensure_all_decoded(item) for item in raw_decode(raw) if item]


def decode_single(item_bytes: object) -> dict[str, NBTData]:
    items = decode(item_bytes)
    if not items:
        raise ItemDecodeError("The item data contains no items.")
    return items[0]
