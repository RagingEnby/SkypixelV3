import io
import json
from base64 import b64decode
from contextlib import suppress
from typing import Any, overload

from nbt import nbt



@overload
def nbt_to_dict(nbt_data: nbt.NBTFile) -> dict: ...
@overload
def nbt_to_dict(nbt_data: nbt.TAG_Compound) -> dict: ...
@overload
def nbt_to_dict(nbt_data: nbt.TAG_List) -> list: ...
@overload
def nbt_to_dict(nbt_data: Any) -> Any: ...
def nbt_to_dict(nbt_data: nbt.NBTFile|nbt.TAG_Compound|nbt.TAG_List|Any) -> dict|list|Any]:
    if isinstance(nbt_data, (nbt.NBTFile, nbt.TAG_Compound)):
        return {tag.name: nbt_to_dict(tag) for tag in nbt_data.tags}
    elif isinstance(nbt_data, nbt.TAG_List):
        return [nbt_to_dict(item) for item in nbt_data.tags]
    return nbt_data.value

def raw_decode(data: bytes) -> list[dict[str, Any]]:
    with io.BytesIO(data) as fileobj:
        parsed_data: dict[str, list[dict[str, Any]]] = nbt_to_dict(nbt.NBTFile(fileobj=fileobj)) # type: ignore [assignment]
        if len(parsed_data) == 1 and 'i' in parsed_data:
            return parsed_data['i']
        else:
            raise ValueError('Invalid item data', data)


def ensure_all_decoded(data: dict[str, Any]|Any) -> dict[str, Any]:
    for k, v in data.items():
        if k == 'petInfo' and isinstance(v, str):
            with suppress(json.JSONDecodeError):
                data[k] = json.loads(v)
        if isinstance(v, dict):
            data[k] = ensure_all_decoded(v)
        elif isinstance(v, list):
            data[k] = [
                ensure_all_decoded(item)
                if isinstance(item, (dict, list))
                else item for item in v
            ]
        elif isinstance(v, bytearray):
            data[k] = str(v)
            #data[k] = raw_decode(v)
    return data



def decode(item_bytes: str) -> list[dict[str, Any]]:
    decoded = [ensure_all_decoded(i) for i in raw_decode(b64decode(item_bytes))]
    return [i for i in decoded if i]


def decode_single(item_bytes: str) -> dict[str, Any]:
    return decode(item_bytes)[0]
