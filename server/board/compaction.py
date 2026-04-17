"""Deprecated compatibility shim. Prefer `server.board.deliberation.compaction`."""

import sys

from server.board.deliberation import compaction as _module

sys.modules[__name__] = _module
