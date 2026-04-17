"""Deprecated compatibility shim. Prefer `server.board.deliberation.orchestrator`."""

import sys

from server.board.deliberation import orchestrator as _module

sys.modules[__name__] = _module
