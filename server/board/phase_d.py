"""Deprecated compatibility shim. Prefer `server.harness.routing_compaction`."""

import sys

from server.harness import routing_compaction as _module

sys.modules[__name__] = _module
