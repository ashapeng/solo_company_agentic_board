"""Deprecated compatibility shim. Prefer `server.board.deliberation.prompts`."""

import sys

from server.board.deliberation import prompts as _module

sys.modules[__name__] = _module
