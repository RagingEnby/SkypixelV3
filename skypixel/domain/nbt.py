import io
import json
from base64 import b64decode
from binascii import Error as Base64Error
from contextlib import suppress
from typing import Any

from nbt import nbt


class ItemDecodeError(ValueError):
    pass


def nbt_to_dict(nbt_data: Any) -> Any:
    if isinstance(nbt_data, (nbt.NBTFile, nbt.TAG_Compound)):
        return {tag.name: nbt_to_dict(tag) for tag in nbt_data.tags}
    if isinstance(nbt_data, nbt.TAG_List):
        return [nbt_to_dict(item) for item in nbt_data.tags]
    return nbt_data.value


def raw_decode(data: bytes) -> list[dict[str, Any]]:
    try:
        with io.BytesIO(data) as fileobj:
            parsed = nbt_to_dict(nbt.NBTFile(fileobj=fileobj))
    except (OSError, EOFError, ValueError, nbt.MalformedFileError) as error:
        raise ItemDecodeError("Cannot decode the item NBT data.") from error
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"i"}
        or not isinstance(parsed["i"], list)
    ):
        raise ItemDecodeError("Expected an NBT item list.")
    return parsed["i"]


def ensure_all_decoded(data: Any) -> Any:
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
        return str(data)
    return data


def decode(item_bytes: str) -> list[dict[str, Any]]:
    try:
        raw = b64decode(item_bytes)
    except (Base64Error, ValueError) as error:
        raise ItemDecodeError("The item data is not valid base64.") from error
    return [ensure_all_decoded(item) for item in raw_decode(raw) if item]


def decode_single(item_bytes: str) -> dict[str, Any]:
    items = decode(item_bytes)
    if not items:
        raise ItemDecodeError("The item data contains no items.")
    return items[0]
