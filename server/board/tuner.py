"""Deprecated compatibility shim. Prefer `server.harness.tuning`."""

import sys

from server.harness import tuning as _module

sys.modules[__name__] = _module
