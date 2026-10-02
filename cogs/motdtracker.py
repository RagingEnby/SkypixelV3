"""Keep the original import path available."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("skypixel.trackers.motdtracker")
