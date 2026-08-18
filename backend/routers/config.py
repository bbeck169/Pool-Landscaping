"""Phase 56.3.A — Runtime public config for the web + mobile clients.

Exposes non-secret keys (Google Maps public JS key, Stripe publishable key)
via a single endpoint so the frontend doesn't have to bake them into the
webpack bundle. Also provides an admin-only health endpoint that reports
whether the Google Maps key is *configured* (without ever hitting Google
from the server — referrer restrictions live in Google Cloud Console and
can't be introspected via the API).
"""
import os

from fastapi import APIRouter, Depends, HTTPException

from utils import require_admin

router = APIRouter()


@router.get("/config/frontend-env")
async def frontend_env():
    """Public — returns non-secret keys the browser needs at runtime.

    Both keys ARE meant to be sent to the client:
      • Stripe publishable keys are prefixed `pk_...` and are public by design.
      • Google Maps JS API keys are visible in-browser once the script loads;
        Google enforces access via HTTP-referrer restrictions on the key
        (configured in Google Cloud Console — see the README).
    """
    return {
        "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY") or "",
        "stripe_publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY") or "",
    }


@router.get("/config/features")
async def config_features():
    """Public runtime feature flags.

    Feb 2026 · Demo-login P0 hotfix #3 — dedicated endpoint that
    returns ONLY the flags a client needs to decide whether to
    render the demo-logins block. Kept separate from
    ``/config/public`` so we can iterate on the contract without
    breaking legacy consumers of ``app_env``.

    ``demo_logins_enabled`` mirrors the ``SHOW_DEMO_LOGINS`` env
    var (default ``false`` → hidden). Any non-truthy value → False,
    matching the fail-closed posture on the client side.
    """
    raw = (os.getenv("SHOW_DEMO_LOGINS") or "").strip().lower()
    return {"demo_logins_enabled": raw in ("1", "true", "yes", "on")}



@router.get("/config/public")
async def config_public():
    """Public runtime flags for the web + mobile clients.

    Feb 2026 · SHOW_DEMO_LOGINS default flip — hide the demo-account
    block by default in production. Preview / dev opt in by setting
    ``SHOW_DEMO_LOGINS=true`` in ``backend/.env``.

    Phase LZ4 · Feb 2026 — this endpoint used to live inside the
    Stripe live-payments router (``payments_stripe_live.py``) so it
    got scooped up when that module was retired. Restored here in
    the natural ``config`` home so the frontend keeps its
    ``show_demo_logins`` gate.

    Feb 2026 · Demo-login P0 hotfix — also expose ``app_env`` so the
    web + mobile login screens can gate the preview-only demo-tiles
    section on the SERVER-SIDE ``APP_ENV`` value at RUNTIME instead
    of a webpack/Metro build-time env var. Build-time envs like
    ``REACT_APP_PUBLIC_ENV`` / ``EXPO_PUBLIC_ENV`` get baked into
    the JS bundle whenever the bundle is built with a preview
    ``.env`` present, and then leak to any production deploy that
    reuses that bundle. Fetching ``app_env`` from the running
    backend eliminates that leak entirely. Missing / unknown values
    fall back to ``"production"`` so the frontend fail-safe path
    (hide the tiles) is the default.
    """
    raw = (os.getenv("SHOW_DEMO_LOGINS") or "").strip().lower()
    show_demo = raw in ("1", "true", "yes", "on")
    app_env = (os.getenv("APP_ENV") or "production").strip().lower()
    if app_env not in ("production", "preview", "development", "staging", "local", "test"):
        app_env = "production"
    return {"show_demo_logins": show_demo, "app_env": app_env}


@router.get("/google-maps/health")
async def google_maps_health(user: dict = Depends(require_admin)):
    """Admin-only — reports whether the Google Maps key is configured.
    Deliberately does NOT hit the Google Maps API — referrer restrictions
    cannot be verified from a server-side request and would generate
    false negatives."""
    return {
        "configured": bool(os.getenv("GOOGLE_MAPS_API_KEY")),
        "referrer_restrictions_note": (
            "Configured in Google Cloud Console — cannot verify from server side."
        ),
    }
