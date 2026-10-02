"""Keep the original cog imports available."""

from skypixel.extensions import EXTENSIONS, get_extension

__all__ = sorted(EXTENSIONS)


def __getattr__(name: str):
    if name in EXTENSIONS:
        return get_extension(name)
    raise AttributeError(name)
