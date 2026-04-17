"""Deprecated compatibility shim. Prefer `server.harness.ledger`."""

import sys

from server.harness import ledger as _module

sys.modules[__name__] = _module
