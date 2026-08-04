"""Phase 34 · Endpoint Path Normalization (Feb 2026)
==================================================

Compatibility alias router for the public review-request token flow.

Background
----------
The mobile client historically calls the 5 public review-request
endpoints at the root prefix (``/api/public/r/*``) while the web client
+ backend router mount them under ``/api/reviews/public/r/*``.

This router mirrors the canonical routes at the mobile prefix so
existing mobile builds keep working, and adds the following headers on
every alias response so the drift is discoverable at request time:

    Deprecation: true
    Link: </api/reviews/public/r/{canonical}>; rel="alternate"

The mobile client is being migrated to the canonical path in the same
phase; this alias is a **one-release-cycle safety net**, not the target
state. Delete once Phase 34+1 ships.

No handler logic is duplicated — each alias defers to the canonical
handler in ``routers/reviews.py``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Response

from . import reviews as _reviews


router = APIRouter()

_CANONICAL_PREFIX = "/api/reviews/public/r"


def _mark_deprecated(response: Response, canonical_suffix: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = (
        f'<{_CANONICAL_PREFIX}/{canonical_suffix}>; rel="alternate"'
    )


@router.get("/public/r/{token}")
async def alias_public_landing(token: str, response: Response):
    _mark_deprecated(response, "{token}")
    return await _reviews.public_landing(token)


@router.post("/public/r/{token}/rating")
async def alias_submit_rating(
    token: str, body: _reviews.RatingIn, response: Response,
):
    _mark_deprecated(response, "{token}/rating")
    return await _reviews.submit_rating(token, body)


@router.post("/public/r/{token}/google-clicked")
async def alias_google_clicked(
    token: str,
    response: Response,
    body: Optional[_reviews.GoogleClickedIn] = None,
):
    _mark_deprecated(response, "{token}/google-clicked")
    return await _reviews.google_clicked(token, body)


@router.post("/public/r/{token}/platform-clicked")
async def alias_platform_clicked(
    token: str, body: _reviews.PlatformClickedIn, response: Response,
):
    _mark_deprecated(response, "{token}/platform-clicked")
    return await _reviews.platform_clicked(token, body)


@router.post("/public/r/{token}/private-feedback")
async def alias_private_feedback(
    token: str, body: _reviews.PrivateFeedbackIn, response: Response,
):
    _mark_deprecated(response, "{token}/private-feedback")
    return await _reviews.private_feedback(token, body)
