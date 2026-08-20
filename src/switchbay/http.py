"""Shared HTTP helpers. Enterprise egress is enforced here."""

from __future__ import annotations

import urllib.request
from typing import Any
from urllib.request import Request

from . import admin_policy


def assert_egress(url: str) -> None:
    if not admin_policy.egress_allowed(url):
        raise PermissionError(admin_policy.feature_error("egress") + f": {url}")


def urlopen(req: str | Request, timeout: float | None = 30, **kwargs: Any):
    url = req if isinstance(req, str) else req.get_full_url()
    assert_egress(url)
    return urllib.request.urlopen(req, timeout=timeout, **kwargs)
