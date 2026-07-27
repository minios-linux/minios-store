"""Shared pytest fixtures and path/stub setup for the MiniOS Store test suite.

This root conftest makes the ``client`` package importable (as
``minios_store``) and the ``tools`` scripts importable by their module
names, and installs a minimal ``websockets`` stub when the real library
is not present (so ``server.py`` can be imported in CI without the dep).
"""

import os
import sys
import types

_ROOT = os.path.dirname(__file__)
_CLIENT = os.path.join(_ROOT, "client")
_TOOLS = os.path.join(_ROOT, "tools")

for _path in (_CLIENT, _TOOLS):
    if _path not in sys.path:
        sys.path.insert(0, _path)


# ---------------------------------------------------------------------------
# Minimal websockets stub (only what server.py touches at import/runtime)
# ---------------------------------------------------------------------------
if "websockets" not in sys.modules:
    _ws = types.ModuleType("websockets")

    class _ConnectionClosed(Exception):
        """Stand-in for websockets.exceptions.ConnectionClosed."""

        def __init__(self, code=1000, reason=""):
            super().__init__(reason)
            self.code = code
            self.reason = reason

    _ws.exceptions = types.SimpleNamespace(ConnectionClosed=_ConnectionClosed)

    async def _serve(*_args, **_kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError("websockets.serve stub")

    _ws.serve = _serve
    sys.modules["websockets"] = _ws
