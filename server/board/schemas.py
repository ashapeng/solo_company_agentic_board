"""Deprecated compatibility shim. Prefer `server.board.projection`."""

import sys

from server.board import projection as _module

sys.modules[__name__] = _module
