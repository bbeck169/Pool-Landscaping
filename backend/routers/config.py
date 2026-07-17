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
