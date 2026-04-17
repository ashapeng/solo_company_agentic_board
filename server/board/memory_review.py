"""Deprecated compatibility shim. Prefer `server.memory.review`."""

import sys

from server.memory import review as _module

sys.modules[__name__] = _module
