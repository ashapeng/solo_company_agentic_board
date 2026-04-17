"""Deprecated compatibility shim. Prefer `server.harness.config`."""

import sys

from server.harness import config as _module

sys.modules[__name__] = _module
