"""Deprecated compatibility shim. Prefer `server.harness.model_assignment`."""

import sys

from server.harness import model_assignment as _module

sys.modules[__name__] = _module
