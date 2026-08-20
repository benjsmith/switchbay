"""Shared HTTP helpers. Enterprise egress is enforced here.

``install_gates()`` wraps ``aiohttp.ClientSession._request`` and
``urllib.request.urlopen`` process-wide so a missed call site cannot
bypass the allowlist. Open profile allows every host.
"""

from __future__ import annotations

import urllib.request
from typing import Any
from urllib.request import Request

import aiohttp

from . import admin_policy

_installed = False
_orig_urlopen = urllib.request.urlopen
_orig_request = aiohttp.ClientSession._request


def assert_egress(url: str) -> None:
    if not admin_policy.egress_allowed(str(url)):
        raise PermissionError(admin_policy.feature_error("egress") + f": {url}")


def urlopen(req: str | Request, *args: Any, **kwargs: Any):
    url = req if isinstance(req, str) else req.get_full_url()
    assert_egress(url)
    return _orig_urlopen(req, *args, **kwargs)


async def _gated_request(self: Any, method: str, url: Any, **kwargs: Any):
    assert_egress(str(url))
    return await _orig_request(self, method, url, **kwargs)


def session(**kwargs: Any) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(**kwargs)


def install_gates() -> None:
    """Patch stdlib + aiohttp. Idempotent."""
    global _installed
    if _installed:
        return
    urllib.request.urlopen = urlopen  # type: ignore[assignment]
    aiohttp.ClientSession._request = _gated_request  # type: ignore[method-assign]
    _installed = True
