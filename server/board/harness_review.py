"""Deprecated compatibility shim. Prefer `server.harness.reviews`."""

import sys

from server.harness import reviews as _module

sys.modules[__name__] = _module
