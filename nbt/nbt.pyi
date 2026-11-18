# Type stub for the parts of the vendored NBT library that Skypixel uses.
from typing import IO, ClassVar

class MalformedFileError(Exception): ...

# The value a leaf tag holds after parsing.
type TagValue = int | float | str | bytearray | list[int] | None

class TAG:
    id: ClassVar[int | None]
    # Parsed tags always carry a name. A tag built in code can hold None, but
    # Skypixel only reads names from parsed data.
    name: str
    value: TagValue
    def __init__(self, value: TagValue = None, name: str | None = None) -> None: ...
    def _render_buffer(self, buffer: IO[bytes]) -> None: ...

class _TAG_Numeric(TAG):
    def __init__(
        self,
        value: int | float | None = None,
        name: str | None = None,
        buffer: IO[bytes] | None = None,
    ) -> None: ...

class TAG_Byte(_TAG_Numeric): ...
class TAG_Short(_TAG_Numeric): ...
class TAG_Int(_TAG_Numeric): ...
class TAG_Long(_TAG_Numeric): ...
class TAG_Float(_TAG_Numeric): ...
class TAG_Double(_TAG_Numeric): ...

class TAG_String(TAG):
    def __init__(
        self,
        value: str | None = None,
        name: str | None = None,
        buffer: IO[bytes] | None = None,
    ) -> None: ...

class TAG_List(TAG):
    tagID: int | None
    tags: list[TAG]
    def __init__(
        self,
        type: type[TAG] | None = None,
        value: TagValue = None,
        name: str | None = None,
        buffer: IO[bytes] | None = None,
    ) -> None: ...

class TAG_Compound(TAG):
    tags: list[TAG]
    def __init__(
        self, buffer: IO[bytes] | None = None, name: str | None = None
    ) -> None: ...

class NBTFile(TAG_Compound):
    def __init__(
        self,
        filename: str | None = None,
        buffer: IO[bytes] | None = None,
        fileobj: IO[bytes] | None = None,
    ) -> None: ...
    def write_file(
        self,
        filename: str | None = None,
        buffer: IO[bytes] | None = None,
        fileobj: IO[bytes] | None = None,
    ) -> None: ...
