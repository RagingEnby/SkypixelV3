__all__ = ["nbt"]
from . import *

VERSION = (1, 5, 1)
"""NBT version as tuple. Note that the major and minor revision number are 
always present, but the patch identifier (the 3rd number) is only used in 1.4."""

def _get_version():
    """Return the NBT version as string."""
    return ".".join([str(v) for v in VERSION])
