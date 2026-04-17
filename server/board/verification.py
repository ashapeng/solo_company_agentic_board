"""Deprecated compatibility shim. Prefer `server.board.deliberation.verification`."""

import sys

from server.board.deliberation import verification as _module

sys.modules[__name__] = _module
