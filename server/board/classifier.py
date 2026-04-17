"""Deprecated compatibility shim. Prefer `server.board.deliberation.classifier`."""

import sys

from server.board.deliberation import classifier as _module

sys.modules[__name__] = _module
