"""Strict browser-controlled Origin boundary shared by Console mutations."""
from __future__ import annotations

from fastapi import Request


def console_origin_allowed(request: Request, *, expected_origin: str | None = None, required: bool = True) -> bool:
    if request.headers.get("sec-fetch-site") in {"cross-site", "none"}:
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return not required
    return origin == (expected_origin or f"{request.url.scheme}://{request.url.netloc}")
