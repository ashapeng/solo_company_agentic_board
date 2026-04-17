"""Deprecated compatibility shim. Prefer `server.memory.sotb`."""

import sys

from server.memory import sotb as _module

sys.modules[__name__] = _module
