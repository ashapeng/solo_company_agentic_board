"""Deprecated compatibility shim. Prefer `server.execution`."""

import sys

import server.execution as _module

sys.modules[__name__] = _module
