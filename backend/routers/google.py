"""Phase 10.5 — Google Maps integration (address geocoding backfill + settings toggles).

Exposes:
- POST /api/admin/geocode-addresses     — backfill customer/job lat/lng from Google Geocoding
- GET/PUT /api/settings/maps            — map provider + autocomplete toggles
- GET  /api/settings/integrations       — masked view of all wired API keys
"""
import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import (
    db, logger,
    GOOGLE_API_KEY, EMERGENT_LLM_KEY, RESEND_API_KEY,
    OPENWEB_NINJA_API_KEY,
)
from utils import now_iso, require_admin, require_admin_or_manager
from routers.tenants import get_current_tenant

router = APIRouter()

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


async def _geocode_one(client: httpx.AsyncClient, address: str) -> Optional[dict]:
    try:
        r = await client.get(GEOCODE_URL, params={"address": address, "key": GOOGLE_API_KEY})
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get("status") != "OK" or not j.get("results"):
            return None
        top = j["results"][0]
        loc = top.get("geometry", {}).get("location", {})
        return {
            "lat": loc.get("lat"), "lng": loc.get("lng"),
            "formatted": top.get("formatted_address"),
            "place_id": top.get("place_id"),
        }
    except Exception as e:
        logger.warning(f"geocode failed for '{address}': {e}")
        return None


@router.post("/admin/geocode-addresses")
async def geocode_addresses(admin: dict = Depends(require_admin)):
    """Backfill lat/lng on customers + jobs that have an address but no coordinates.
    Rate-limited at ~8 req/sec to stay well under Google's default 50 QPS."""
    if not GOOGLE_API_KEY:
        raise HTTPException(424, "GOOGLE_API_KEY not configured")

    processed = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=15) as client:
        # ── customers ──
        q = {
            "address": {"$exists": True, "$nin": [None, ""]},
            "$or": [{"lat": {"$in": [None, 0]}}, {"lat": {"$exists": False}}],
        }
        async for c in db.customers.find(q, {"_id": 0}):
            processed += 1
            addr = c.get("address")
            if not addr:
                skipped += 1
                continue
            geo = await _geocode_one(client, addr)
            if geo and geo.get("lat"):
                await db.customers.update_one({"id": c["id"]}, {"$set": {
                    "lat": geo["lat"], "lng": geo["lng"],
                    "geocoded_address": geo.get("formatted"),
                    "geocoded_place_id": geo.get("place_id"),
                    "geocoded_at": now_iso(),
                }})
                updated += 1
            else:
                errors.append(c.get("name") or c["id"])
            await asyncio.sleep(0.12)  # ~8 QPS

        # ── jobs (service_address / address fields) ──
        jq = {
            "$or": [
                {"address": {"$exists": True, "$nin": [None, ""]}},
                {"service_address": {"$exists": True, "$nin": [None, ""]}},
            ],
            "$and": [{"$or": [{"lat": {"$in": [None, 0]}}, {"lat": {"$exists": False}}]}],
        }
        async for j in db.jobs.find(jq, {"_id": 0}):
            processed += 1
            addr = j.get("service_address") or j.get("address")
            if not addr:
                skipped += 1
                continue
            geo = await _geocode_one(client, addr)
            if geo and geo.get("lat"):
                await db.jobs.update_one({"id": j["id"]}, {"$set": {
                    "lat": geo["lat"], "lng": geo["lng"],
                    "geocoded_address": geo.get("formatted"),
                    "geocoded_at": now_iso(),
                }})
                updated += 1
            else:
                errors.append(j.get("title") or j["id"])
            await asyncio.sleep(0.12)

    return {
        "processed": processed, "updated": updated, "skipped": skipped,
        "errors": errors[:20], "error_count": len(errors),
    }


# ─── settings/maps ─────────────────────────────────────────────────────────
class MapSettingsIn(BaseModel):
    map_provider: Optional[str] = None          # "openstreetmap" | "google"
    autocomplete_enabled: Optional[bool] = None


DEFAULT_MAP_SETTINGS = {
    "map_provider": "openstreetmap",
    "autocomplete_enabled": True,
}


@router.get("/settings/maps")
async def get_map_settings(admin: dict = Depends(require_admin)):
    doc = await db.settings.find_one({"id": "maps"}, {"_id": 0}) or {}
    return {
        "map_provider": doc.get("map_provider") or DEFAULT_MAP_SETTINGS["map_provider"],
        "autocomplete_enabled": doc.get("autocomplete_enabled") if doc.get("autocomplete_enabled") is not None else DEFAULT_MAP_SETTINGS["autocomplete_enabled"],
        "google_configured": bool(GOOGLE_API_KEY),
    }


@router.put("/settings/maps")
async def put_map_settings(body: MapSettingsIn, admin: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd.get("map_provider") not in (None, "openstreetmap", "google"):
        raise HTTPException(400, "map_provider must be 'openstreetmap' or 'google'")
    await db.settings.update_one(
        {"id": "maps"},
        {"$set": {"id": "maps", **upd, "updated_at": now_iso()}},
        upsert=True,
    )
    return await get_map_settings(admin)


# Public read for frontend so the map provider is available WITHOUT admin token.
@router.get("/public/map-settings")
async def public_map_settings():
    doc = await db.settings.find_one({"id": "maps"}, {"_id": 0}) or {}
    return {
        "map_provider": doc.get("map_provider") or DEFAULT_MAP_SETTINGS["map_provider"],
        "autocomplete_enabled": doc.get("autocomplete_enabled") if doc.get("autocomplete_enabled") is not None else DEFAULT_MAP_SETTINGS["autocomplete_enabled"],
        "google_configured": bool(GOOGLE_API_KEY),
    }


# ─── settings/integrations ─────────────────────────────────────────────────
@router.get("/settings/integrations")
async def get_integrations_status(admin: dict = Depends(require_admin)):
    """Report the wiring status of all third-party integrations. Keys are masked."""
    import os
    stripe_key = os.environ.get("STRIPE_API_KEY", "") or os.environ.get("STRIPE_SECRET_KEY", "")
    resend_from = os.environ.get("EMAIL_FROM", "")
    stripe_wh = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    wp_url = os.environ.get("WORDPRESS_URL", "")
    gbp_client = os.environ.get("GBP_CLIENT_ID", "")
    # Feb-2026 · Twilio removed — RingCentral is the sole SMS provider.
    rc_client_id = os.environ.get("RC_CLIENT_ID", "")
    ring_key = ""
    ring_doc = await db.settings.find_one({"id": "ringcentral"}, {"_id": 0}) or {}
    if ring_doc.get("api_key"):
        ring_key = ring_doc["api_key"]
    return {
        "emergent_llm":    {"configured": bool(EMERGENT_LLM_KEY),        "preview": _mask(EMERGENT_LLM_KEY),      "note": "OpenAI / Claude / Gemini via Emergent"},
        "google":          {"configured": bool(GOOGLE_API_KEY),          "preview": _mask(GOOGLE_API_KEY),        "note": "Places autocomplete · Geocoding · Maps tiles"},
        "openweb_ninja":   {"configured": bool(OPENWEB_NINJA_API_KEY),   "preview": _mask(OPENWEB_NINJA_API_KEY), "note": "Zillow sold-lead data for D2D"},
        "resend":          {"configured": bool(RESEND_API_KEY),          "preview": _mask(RESEND_API_KEY),        "note": f"Transactional email · from {resend_from}"},
        "stripe":          {"configured": bool(stripe_key),              "preview": _mask(stripe_key),            "note": "Card payments (test mode)"},
        "stripe_webhook":  {"configured": bool(stripe_wh),               "preview": _mask(stripe_wh),             "note": "Webhook signing secret · unsigned fallback active if missing"},
        "wordpress":       {"configured": bool(wp_url),                  "preview": _mask(wp_url),                "note": "SEO article publishing"},
        "gbp":             {"configured": bool(gbp_client),              "preview": _mask(gbp_client),            "note": "Google Business Profile OAuth (Client ID)"},
        "ringcentral":     {"configured": bool(rc_client_id or ring_key), "preview": _mask(rc_client_id or ring_key), "note": "SMS delivery + inbound call tracking"},
    }


@router.get("/settings/integrations/health/comms")
async def integration_health_comms(
    admin: dict = Depends(require_admin_or_manager),
):
    """Feb-2026 P0 · Comms end-to-end diagnostic (admin/manager only).

    Returns a single snapshot of every gate + provider config that
    can silently suppress an outbound Email / SMS in the running
    process. This is the "one curl" replacement for the previous
    Mongo-shell walkthrough (see the P0 diagnostic report).

    Multi-tenant note: this endpoint reports PROCESS-level config
    (env vars, in-process singletons). The one Mongo-level check
    (``rc_settings.outbound_enabled``) is a **global** RC toggle
    stored WITHOUT ``tenant_id``, per the current schema, so it
    reports uniformly across tenants — that matches the current
    single-RC-tenant deployment.
    """
    import os
    from services.comms.gate import current_gate_policy
    from services.comms_env_guard import (
        is_production as _is_prod,
        last_startup_banner_iso as _banner_iso,
    )
    from services.ringcentral_client import (
        is_outbound_enabled as _rc_outbound_enabled_runtime,
    )

    notes: list[str] = []

    # ── App env ──
    app_env = (os.environ.get("APP_ENV") or "preview").strip().lower()
    is_prod = _is_prod()
    if not is_prod:
        notes.append(
            f"APP_ENV={app_env!r} (not 'production'); guard_outbound "
            "will dry-run every send unless recipient is on "
            "COMMS_TEST_ALLOWLIST_EMAILS/PHONES.")

    # ── Resend ──
    resend_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    resend_configured = bool(resend_key) and not resend_key.startswith(
        "re_placeholder")
    resend_from = (
        os.environ.get("RESEND_FROM_ADDRESS")
        or os.environ.get("EMAIL_FROM")
        or os.environ.get("RESEND_FROM")
        or None
    )
    if resend_from:
        resend_from = resend_from.strip('"').strip("'")
    verified_raw = (os.environ.get("RESEND_VERIFIED_DOMAINS")
                      or "resend.dev").strip()
    verified_domains = sorted({
        d.strip().lower() for d in verified_raw.split(",") if d.strip()
    })
    if not resend_configured:
        notes.append("RESEND_API_KEY unset or placeholder; email sends "
                       "will return provider_status='mocked'.")

    # ── RingCentral ──
    rc_client_id = os.environ.get("RC_CLIENT_ID") or ""
    rc_client_secret = os.environ.get("RC_CLIENT_SECRET") or ""
    rc_jwt = os.environ.get("RC_JWT") or ""
    rc_configured = bool(rc_client_id and rc_client_secret and rc_jwt)
    rc_mode = os.environ.get("RC_MODE") or None
    rc_env_val = (os.environ.get("RC_OUTBOUND_ENABLED") or "").lower()
    rc_env_enabled = rc_env_val == "true"
    # Mongo toggle — wins over env at runtime. ``None`` when the doc
    # is absent (env then applies).
    rc_mongo_enabled: "bool | None" = None
    try:
        row = await db.rc_settings.find_one(
            {"key": "outbound_enabled"}, {"_id": 0, "value": 1},
        )
        if row is not None:
            rc_mongo_enabled = bool(row.get("value"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"comms-health: rc_settings read failed: {exc}")
    try:
        rc_effective_outbound = await _rc_outbound_enabled_runtime()
    except Exception:  # noqa: BLE001
        rc_effective_outbound = rc_env_enabled
    if not rc_effective_outbound:
        if rc_mongo_enabled is False:
            notes.append("rc_settings.outbound_enabled=false in Mongo — "
                          "overrides RC_OUTBOUND_ENABLED env. Delete the "
                          "doc or PUT true via /admin/settings/ringcentral.")
        elif not rc_env_enabled:
            notes.append("RC_OUTBOUND_ENABLED != 'true' — SMS notification "
                          "path (_dispatch_sms) will record delivery_status="
                          "'mocked'.")

    # ── SMS mock (campaign adapter) ──
    sms_mock_raw = os.environ.get("SMS_MOCK_MODE")
    # Adapter defaults to "1" when unset — strict compare in
    # services/comms_sms_adapter.py:87.
    sms_will_mock = (sms_mock_raw or "1") == "1"
    if sms_will_mock:
        notes.append("SMS_MOCK_MODE defaults to mock (adapter treats "
                      "anything != '0' as mock). Set SMS_MOCK_MODE=0 for "
                      "live campaign-broadcast SMS.")

    # ── Resend SDK monkey-patch presence ──
    monkey_patch_installed = False
    try:
        import resend as _resend  # type: ignore
        monkey_patch_installed = bool(getattr(
            getattr(_resend, "Emails", None),
            "_aquaterra_gated_send", False,
        ))
    except Exception:  # noqa: BLE001
        monkey_patch_installed = False

    # ── Gate policy ──
    gate_policy = current_gate_policy()
    if gate_policy == "demo_only":
        notes.append("Gate policy is 'demo_only' — only recipients with "
                      "is_demo_account=True clear the gate. Flip APP_ENV to "
                      "'production' to switch to 'prod_bypass'.")

    return {
        "app_env": app_env,
        "is_production": is_prod,
        "gate_policy": gate_policy,
        "resend_api_key_configured": resend_configured,
        "resend_from": resend_from,
        "resend_verified_domains": verified_domains,
        "ringcentral_configured": rc_configured,
        "rc_outbound_enabled_env": rc_env_enabled,
        "rc_outbound_enabled_mongo": rc_mongo_enabled,
        "rc_outbound_enabled_effective": bool(rc_effective_outbound),
        "rc_mode": rc_mode,
        "sms_mock_mode": sms_mock_raw,
        "sms_will_mock": sms_will_mock,
        "monkey_patch_installed": monkey_patch_installed,
        "startup_banner_last_seen": _banner_iso(),
        "notes": notes,
    }


@router.get("/settings/integrations/health/checkout-preflight")
async def integration_health_checkout_preflight(
    admin: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Feb-2026 P0 · Stripe Checkout preflight (admin/manager only).

    Runs the SAME code path as ``POST /api/invoices/{id}/request-payment-link``
    against a synthetic in-memory invoice + customer so we can see
    the EXACT Stripe SDK exception that a real click would surface
    on this pod. Never persists a real invoice or customer. Uses a
    ``preflight:`` idempotency key + immediately expires the created
    Checkout Session so we don't clutter the live Stripe dashboard.

    Reads env vars via ``os.environ.get`` so a supervisor reload of
    ``.env`` takes effect without a Python-import round-trip.
    """
    import os
    import uuid as _uuid

    from services.payments import stripe_charge as _stripe_svc

    out: dict = {
        "ok": False,
        "app_env": (os.environ.get("APP_ENV") or "").strip().lower(),
        "stripe_mode": None,
        "stripe_account_id": None,
        "app_public_url": os.environ.get("APP_PUBLIC_URL") or None,
        "stripe_secret_key_live_set": bool(
            os.environ.get("STRIPE_SECRET_KEY_LIVE")),
        "stripe_webhook_secret_live_set": bool(
            os.environ.get("STRIPE_WEBHOOK_SECRET_LIVE")),
        "checkout_session_created": False,
        "checkout_url_preview": None,
        "error_class": None,
        "error_message": None,
        "hint": None,
    }

    # Snapshot mode + account before we try the round-trip — even
    # if the round-trip fails, ops still see what mode the pod
    # THINKS it's in.
    try:
        out["stripe_mode"] = _stripe_svc._mode()
    except Exception:  # noqa: BLE001
        pass

    synth_id = f"preflight-{_uuid.uuid4().hex[:12]}"
    synth_invoice = {
        "id": synth_id,
        "invoice_number": f"PF-{synth_id[-6:]}",
        "total": 1.00,
        "amount_paid": 0.00,
        "currency": "usd",
        "tenant_id": tenant["id"],
    }
    synth_customer = {
        # ``customer.id`` is only used for Stripe metadata — never
        # persisted, never billed.
        "id": f"preflight-customer-{_uuid.uuid4().hex[:8]}",
        "email": "preflight@plofv.com",
    }

    try:
        result = await _stripe_svc.create_invoice_checkout_session(
            tenant_id=tenant["id"],
            invoice=synth_invoice,
            customer=synth_customer,
        )
        out["checkout_session_created"] = True
        out["checkout_url_preview"] = (result.get("payment_url") or "")[:80]
        out["stripe_mode"] = result.get("mode") or out["stripe_mode"]
        # Best-effort — capture Stripe account so ops sees which
        # account key is loaded (live vs test).
        try:
            import stripe as _stripe  # type: ignore
            _stripe.api_key = _stripe_svc._select_secret_key()
            acct = _stripe.Account.retrieve()
            # Stripe v7+ returns a ``StripeObject``; both attribute and
            # subscript access work but not dict.get(). Prefer id attr.
            out["stripe_account_id"] = getattr(acct, "id", None) or acct["id"]
        except Exception:  # noqa: BLE001
            pass
        # Cleanup — immediately expire the Session so it never
        # transacts. Best-effort; failure here does NOT flip ``ok``.
        try:
            import stripe as _stripe  # type: ignore
            _stripe.checkout.Session.expire(
                result.get("checkout_session_id"))
        except Exception as _exc:  # noqa: BLE001
            logger.warning(
                f"[preflight] session.expire best-effort failed: {_exc}")
        out["ok"] = True
        out["hint"] = ("Stripe checkout is fully reachable on this pod. "
                        "If real ``request-payment-link`` calls still 502 "
                        "in the browser, inspect the specific invoice's "
                        "``customer_id`` / ``total`` / ``payment_status`` "
                        "for guard-condition mismatches.")
        return out
    except _stripe_svc._UnconfiguredStripeError as exc:
        out["error_class"] = "_UnconfiguredStripeError"
        out["error_message"] = str(exc)[:400]
        out["hint"] = (
            "No Stripe secret key is present in this pod's environment. "
            "Set STRIPE_SECRET_KEY_LIVE (for STRIPE_MODE=live) or "
            "STRIPE_SECRET_KEY_TEST (STRIPE_MODE=test) and restart the "
            "backend.")
        return out
    except ValueError as exc:
        out["error_class"] = "ValueError"
        out["error_message"] = str(exc)[:400]
        if "APP_PUBLIC_URL" in str(exc):
            out["hint"] = ("APP_PUBLIC_URL env var is missing on this pod. "
                            "Set APP_PUBLIC_URL=https://app.plofv.com and "
                            "restart the backend.")
        else:
            out["hint"] = ("Business-logic guard blocked the preflight — "
                            "unlikely on a synthetic $1 invoice; treat as "
                            "an unexpected code-side regression.")
        return out
    except Exception as exc:  # noqa: BLE001
        # Every remaining path — stripe.error.AuthenticationError,
        # stripe.error.APIConnectionError, stripe.error.InvalidRequestError,
        # stripe.error.RateLimitError, etc. Report the class + message
        # verbatim so ops sees exactly what Stripe returned.
        out["error_class"] = type(exc).__name__
        out["error_message"] = str(exc)[:400]
        cls = out["error_class"]
        if cls == "AuthenticationError":
            out["hint"] = ("STRIPE_SECRET_KEY_LIVE is present but INVALID "
                            "(rotated, wrong account, or missing scopes). "
                            "Re-copy the key from Stripe dashboard → "
                            "Developers → API keys → Live secret key.")
        elif cls == "APIConnectionError":
            out["hint"] = ("Pod cannot reach ``api.stripe.com`` (network "
                            "egress problem or Cloudflare block). Confirm "
                            "outbound HTTPS is open.")
        elif cls == "InvalidRequestError":
            out["hint"] = ("Stripe rejected the request body — likely a "
                            "malformed line_item or missing metadata. "
                            "Escalate for code-side review.")
        elif cls == "RateLimitError":
            out["hint"] = ("Stripe rate-limited this key. Wait 60s then "
                            "retry.")
        else:
            out["hint"] = ("Unexpected Stripe SDK exception. Full class "
                            f"name: {cls}. Escalate for code-side review.")
        logger.warning(
            f"[preflight] Stripe SDK exception class={cls} msg={exc}")
        return out


@router.get("/settings/integrations/health/{integration}")
async def integration_health(integration: str, admin: dict = Depends(require_admin)):
    """Lightweight liveness check for the specified integration."""
    import os

    def _mask_key(text: str, key: str) -> str:
        """Replace any occurrence of the API key value in the text
        with ``***MASKED***`` so a Resend echo-back never leaks the
        secret through this endpoint. Also masks the first 8 chars
        as a substring defense (Resend prefixes error responses with
        request context in some edge cases)."""
        if not text or not key:
            return text
        masked = text.replace(key, "***MASKED***")
        prefix = key[:8]
        if len(prefix) >= 6:
            masked = masked.replace(prefix, "***")
        return masked

    try:
        if integration == "google":
            if not GOOGLE_API_KEY: return {"ok": False, "message": "GOOGLE_API_KEY unset"}
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(GEOCODE_URL, params={"address": "10840 W Saddlehorn Rd, Peoria AZ", "key": GOOGLE_API_KEY})
                j = r.json() if r.status_code == 200 else {}
            return {"ok": j.get("status") == "OK", "message": j.get("status", f"HTTP {r.status_code}")}
        if integration == "openweb_ninja":
            if not OPENWEB_NINJA_API_KEY: return {"ok": False, "message": "OPENWEB_NINJA_API_KEY unset"}
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://api.openwebninja.com/realtime-zillow-data/search_zip",
                                params={"zip": "85383"}, headers={"x-api-key": OPENWEB_NINJA_API_KEY})
            return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
        if integration == "resend":
            key = os.environ.get("RESEND_API_KEY", "")
            if not key:
                return {"ok": False, "message": "RESEND_API_KEY unset"}
            # Phase 27.1 · Feb 2026 — expose the actual Resend response
            # body on failure so admins can distinguish "invalid API
            # key" from "missing scope" from "domain quota" without
            # spelunking through pod logs. On success, include the
            # verified-domains list. NEVER echoes the API key value
            # itself — the ``_mask_key`` helper below is applied to any
            # accidental key-substring in the Resend response.
            try:
                async with httpx.AsyncClient(timeout=8) as c:
                    r = await c.get(
                        "https://api.resend.com/domains",
                        headers={"Authorization": f"Bearer {key}"},
                    )
            except Exception as e:
                return {"ok": False, "message": f"unreachable: {str(e)[:200]}"}
            body_snippet = _mask_key((r.text or "")[:400], key)
            if r.status_code == 200:
                try:
                    payload = r.json() or {}
                    raw_domains = payload.get("data") or payload.get("domains") or []
                    domains = []
                    for d in raw_domains:
                        if not isinstance(d, dict):
                            continue
                        domains.append({
                            "name": d.get("name"),
                            "status": d.get("status"),
                            "region": d.get("region"),
                        })
                except Exception:
                    domains = []
                return {"ok": True, "message": "HTTP 200",
                        "domains": domains,
                        "domain_count": len(domains)}
            # Non-200 — parse the error name/message if Resend returned JSON.
            resend_error = None
            try:
                j = r.json()
                if isinstance(j, dict):
                    resend_error = {
                        "name": j.get("name"),
                        "message": _mask_key(str(j.get("message") or "")[:200], key),
                        "statusCode": j.get("statusCode"),
                    }
            except Exception:
                pass
            return {
                "ok": False,
                "message": f"HTTP {r.status_code}",
                "resend_error": resend_error,
                "response_body": body_snippet if not resend_error else None,
            }
        if integration == "stripe":
            # Feb-2026 · Option-A revert · real health probe restoring
            # the Phase 47d truth: Stripe is the primary payment
            # provider. The Phase LZ4 "retired" stub was leftover
            # from a since-reverted decision.
            #
            # Probe strategy:
            #   1. Pick the secret key for the active ``STRIPE_MODE``.
            #   2. If no key → ok=false with a "key unset" message.
            #   3. Call ``stripe.Account.retrieve()`` via ``asyncio
            #      .to_thread`` with a 3-second timeout. Success →
            #      ok=true. Auth error → surface the real message.
            #   4. If the ``stripe`` SDK isn't importable, fall back
            #      to key-presence only so the panel doesn't stall.
            mode = (os.environ.get("STRIPE_MODE") or "test").lower()
            key_var = ("STRIPE_SECRET_KEY_LIVE" if mode == "live"
                       else "STRIPE_SECRET_KEY_TEST")
            key = (os.environ.get(key_var) or "").strip()
            if not key:
                return {"ok": False,
                        "message": f"{key_var} unset (STRIPE_MODE={mode})"}
            try:
                import stripe as _stripe  # type: ignore
            except Exception:
                return {"ok": True,
                        "message": "Key present (SDK not loaded)",
                        "stripe_mode": mode}
            try:
                _stripe.api_key = key
                acct = await asyncio.wait_for(
                    asyncio.to_thread(_stripe.Account.retrieve),
                    timeout=3.0,
                )
                return {
                    "ok": True,
                    "message": "HTTP 200",
                    "stripe_mode": mode,
                    "account_id": getattr(acct, "id", None),
                    "livemode": getattr(acct, "livemode", None),
                }
            except asyncio.TimeoutError:
                return {"ok": False, "stripe_mode": mode,
                        "message": "timeout after 3s"}
            except Exception as e:
                # ``stripe.error.*`` exceptions carry ``.user_message``.
                msg = getattr(e, "user_message", None) or str(e)[:200]
                return {"ok": False, "stripe_mode": mode,
                        "message": msg}
        if integration == "emergent_llm":
            return {"ok": bool(EMERGENT_LLM_KEY), "message": "Key present" if EMERGENT_LLM_KEY else "unset"}
        if integration == "wordpress":
            # Feb-2026 · real reachability probe against
            # ``/wp-json/wp/v2/users/me`` using Basic Auth with the
            # Application Password. Returns:
            #   * ok=true, HTTP 200 + user name — fully wired
            #   * ok=false, HTTP 401 — creds wrong
            #   * ok=false, HTTP 202 + text/html — WAF interstitial
            #     (SiteGround SG-Optimizer, Cloudflare bot manager,
            #     etc.) — user must whitelist our egress IP
            #   * ok=false, unset — no env config
            wp_url = os.environ.get("WORDPRESS_URL", "").strip().rstrip("/")
            wp_user = (os.environ.get("WORDPRESS_USERNAME")
                         or os.environ.get("WORDPRESS_USER") or "").strip()
            wp_pw = os.environ.get("WORDPRESS_APP_PASSWORD", "").strip()
            if not (wp_url and wp_user and wp_pw):
                return {"ok": False,
                          "message": "WORDPRESS_URL / WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD unset"}
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        f"{wp_url}/wp-json/wp/v2/users/me",
                        auth=(wp_user, wp_pw),
                        headers={"Accept": "application/json",
                                   "User-Agent": "PlofvCRM/1.0 (+wp-health-check)"},
                    )
            except Exception as e:
                return {"ok": False, "message": f"unreachable: {e}"[:200]}
            ct = (r.headers.get("content-type") or "").lower()
            if r.status_code == 200 and "json" in ct:
                try:
                    name = (r.json() or {}).get("name") or wp_user
                except Exception:
                    name = wp_user
                return {"ok": True, "message": f"HTTP 200 · authed as {name}"}
            if r.status_code == 401:
                return {"ok": False,
                          "message": "HTTP 401 — Application Password rejected"}
            if r.status_code == 202 or ("html" in ct and "sgcaptcha" in r.text.lower()):
                return {"ok": False,
                          "message": "Blocked by SiteGround SG-Optimizer WAF — "
                                       "whitelist the pod egress IP or disable "
                                       "SG bot protection for /wp-json/*"}
            return {"ok": False,
                      "message": f"HTTP {r.status_code} ({ct[:40] or 'unknown ct'})"}
        if integration in {"gbp", "ringcentral", "stripe_webhook"}:
            # Not enough config wired yet to actually ping — report presence only.
            keymap = {
                "gbp": "GBP_CLIENT_ID",
                "wordpress": "WORDPRESS_URL", "ringcentral": "RC_CLIENT_ID",
                "stripe_webhook": "STRIPE_WEBHOOK_SECRET",
            }
            v = os.environ.get(keymap[integration], "")
            return {"ok": bool(v), "message": "Key present" if v else "unset"}
        raise HTTPException(404, "Unknown integration")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"integration health {integration} failed: {e}")
        return {"ok": False, "message": str(e)[:200]}
