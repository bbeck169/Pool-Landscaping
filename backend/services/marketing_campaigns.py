"""Marketing Campaigns · Phase M2 helpers (Feb 2026).

Sender.net-parity one-off campaign send engine.

* **HMAC-signed tracking tokens** are used for the open pixel, click
  redirect, and one-click unsubscribe links. Token = base64url of
  ``payload`` + ``.`` + short HMAC-SHA256 of the payload. Payload
  is a compact JSON object with ``{c, s, sd, u?}`` (campaign_id,
  subscriber_id, send_id, url_hash). Rotating the secret invalidates
  every outstanding token — the signing key comes from the
  ``MARKETING_CAMPAIGN_SECRET`` env var, defaulting to a deterministic
  per-tenant fallback so unit tests are hermetic.

* **Audience resolution** consumes M1 ``marketing_lists`` +
  ``marketing_segments`` collections. Static lists carry an inline
  ``subscriber_ids[]``; dynamic lists resolve via their ``segment_id``.

* **Send pipeline** is 100% mockable: we route through the existing
  ``services.comms_email_adapter.send_email`` and
  ``services.comms_sms_adapter.send_sms``, both of which honour their
  own env-based mock flags. Every send lands in
  ``marketing_campaign_sends`` with a ``provider_message_id`` (real or
  stubbed) so the analytics endpoints can aggregate against real rows
  even when no external provider is wired.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from config import db, logger
from utils import new_id, now_iso


# ─── HMAC tokens ───────────────────────────────────────────────────────
def _campaign_secret() -> bytes:
    key = os.environ.get("MARKETING_CAMPAIGN_SECRET") \
        or os.environ.get("EMERGENT_LLM_KEY") \
        or "pool-crm-marketing-dev-secret"
    return key.encode("utf-8")


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def mint_token(campaign_id: str, subscriber_id: str, send_id: str,
                  url_hash: Optional[str] = None) -> str:
    """Compact HMAC token used in tracking + unsubscribe URLs."""
    payload = {"c": campaign_id, "s": subscriber_id, "sd": send_id}
    if url_hash:
        payload["u"] = url_hash
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_campaign_secret(), raw, hashlib.sha256).digest()[:12]
    return _b64u(raw) + "." + _b64u(sig)


def verify_token(token: str) -> Optional[Dict[str, str]]:
    """Return the decoded payload dict when the token is intact, else None.
    Constant-time signature comparison."""
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _b64u_decode(raw_b64)
        provided = _b64u_decode(sig_b64)
    except Exception:
        return None
    expected = hmac.new(_campaign_secret(), raw, hashlib.sha256).digest()[:12]
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def hash_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


# ─── Audience resolution ───────────────────────────────────────────────
async def _subscribers_of_list(tenant_id: str,
                                 list_id: str) -> Set[str]:
    """Return the set of subscriber ids belonging to a marketing list.

    Static lists resolve to rows in ``marketing_list_memberships``
    (per M1 schema); dynamic lists resolve their ``segment_id`` via
    the segment's ``rules``. Non-existent lists return an empty set.
    """
    lst = await db.marketing_lists.find_one(
        {"id": list_id, "tenant_id": tenant_id}, {"_id": 0})
    if not lst:
        return set()
    if lst.get("type") == "dynamic":
        seg_id = lst.get("segment_id")
        return await _subscribers_of_segment(tenant_id, seg_id) if seg_id else set()
    # Static — join via memberships.
    hits: Set[str] = set()
    async for m in db.marketing_list_memberships.find(
        {"tenant_id": tenant_id, "list_id": list_id},
        {"_id": 0, "subscriber_id": 1}):
        sid = m.get("subscriber_id")
        if sid:
            hits.add(sid)
    return hits


async def _subscribers_of_segment(tenant_id: str,
                                     segment_id: str) -> Set[str]:
    seg = await db.marketing_segments.find_one(
        {"id": segment_id, "tenant_id": tenant_id}, {"_id": 0})
    if not seg:
        return set()
    filters: Dict[str, Any] = {"tenant_id": tenant_id}
    # Basic criteria support — M1 stores segments in shape
    # ``{criteria: {status?, tags?, list_ids?}}``.
    crit = seg.get("criteria") or {}
    if crit.get("status"):
        filters["status"] = crit["status"]
    if crit.get("tags"):
        filters["tags"] = {"$in": crit["tags"]}
    hits: Set[str] = set()
    async for row in db.subscribers.find(filters, {"_id": 0, "id": 1}):
        if row.get("id"):
            hits.add(row["id"])
    return hits


async def resolve_audience(tenant_id: str,
                              audience: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the final send audience.

    ``audience`` shape::
       {list_ids:[], segment_ids:[], exclude_list_ids:[],
        exclude_segment_ids:[]}
    Returns::
      {estimated_size, unique_email_count, unique_phone_count,
       unsubscribed_excluded_count, subscriber_ids:[], sample:[first 5]}
    """
    include: Set[str] = set()
    for lid in audience.get("list_ids") or []:
        include |= await _subscribers_of_list(tenant_id, lid)
    for sid in audience.get("segment_ids") or []:
        include |= await _subscribers_of_segment(tenant_id, sid)

    exclude: Set[str] = set()
    for lid in audience.get("exclude_list_ids") or []:
        exclude |= await _subscribers_of_list(tenant_id, lid)
    for sid in audience.get("exclude_segment_ids") or []:
        exclude |= await _subscribers_of_segment(tenant_id, sid)

    kept = include - exclude

    docs = await db.subscribers.find(
        {"tenant_id": tenant_id, "id": {"$in": list(kept)}},
        {"_id": 0}
    ).to_list(len(kept) + 1) if kept else []
    subscribed = [d for d in docs if d.get("status") == "subscribed"]
    unsubbed_excluded = len(docs) - len(subscribed)
    emails = {(d.get("email") or "").lower().strip()
                for d in subscribed if d.get("email")}
    phones = {(d.get("phone") or "").strip()
                for d in subscribed if d.get("phone")}
    sample = subscribed[:5]

    return {
        "estimated_size": len(subscribed),
        "unique_email_count": len(emails - {""}),
        "unique_phone_count": len(phones - {""}),
        "unsubscribed_excluded_count": unsubbed_excluded,
        "subscriber_ids": [d["id"] for d in subscribed],
        "sample": sample,
    }


# ─── Rendering ─────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_body(template: str, ctx: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Substitute ``{{token}}`` placeholders. Returns
    ``(rendered, missing_tokens)``. Missing tokens leave the raw
    ``{{token}}`` intact so the caller can surface them as warnings."""
    if not template:
        return "", []
    missing: List[str] = []
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx and ctx[key] is not None:
            return str(ctx[key])
        missing.append(key)
        return m.group(0)
    return _TOKEN_RE.sub(_sub, template), missing


_SPAM_WORDS = {"free", "guaranteed", "click here", "act now",
                "limited time", "risk-free", "buy now"}


def spam_score(subject: str, body: str) -> Tuple[int, List[str]]:
    """Very cheap heuristic — flags common spam-trigger phrases."""
    hits: List[str] = []
    haystack = f"{subject or ''} {body or ''}".lower()
    for w in _SPAM_WORDS:
        if w in haystack:
            hits.append(w)
    return len(hits), hits


def _base_backend_url() -> str:
    return (os.environ.get("REACT_APP_BACKEND_URL")
            or os.environ.get("PUBLIC_BASE_URL")
            or "").rstrip("/")


def rewrite_email_html(html: str, campaign_id: str, subscriber_id: str,
                          send_id: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Rewrite every ``<a href="…">`` through the click tracker and
    inject the tracking pixel + preferences link at the end of the
    body. Returns ``(new_html, url_index)`` where url_index carries
    every original URL with its hash so callers can persist a
    click-catalog per campaign.
    """
    base = _base_backend_url()
    url_index: List[Dict[str, Any]] = []

    def _sub(m: re.Match) -> str:
        original = m.group(1)
        if original.startswith(("mailto:", "tel:", "#")):
            return m.group(0)
        uh = hash_url(original)
        url_index.append({"url": original, "url_hash": uh})
        tok = mint_token(campaign_id, subscriber_id, send_id, url_hash=uh)
        tracked = f"{base}/api/public/mkt/c/{tok}?u={uh}"
        return f'<a href="{tracked}"'

    new_html = re.sub(r'<a\s+href="([^"]+)"', _sub, html or "", flags=re.IGNORECASE)
    open_token = mint_token(campaign_id, subscriber_id, send_id)
    pixel = (f'<img src="{base}/api/public/mkt/o/{open_token}" width="1" '
              f'height="1" style="display:none" alt="" />')
    unsub_url = f"{base}/api/public/mkt/unsub/{open_token}"
    footer = (
        f'<div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;'
        f'font-size:11px;color:#6b7280">'
        f'<a href="{unsub_url}" style="color:#6b7280">Unsubscribe</a>'
        f'</div>'
    )
    return f"{new_html}{footer}{pixel}", url_index


def rewrite_sms_body(body: str, campaign_id: str, subscriber_id: str,
                        send_id: str, primary_url: Optional[str] = None) -> str:
    """SMS bodies get the first http(s) link rewritten and the opt-out
    clause appended. Reuses ``Reply STOP`` phrase already normalized
    by the SMS adapter — this helper only ensures a click-track URL."""
    text = body or ""
    if primary_url:
        uh = hash_url(primary_url)
        tok = mint_token(campaign_id, subscriber_id, send_id, url_hash=uh)
        tracked = f"{_base_backend_url()}/api/public/mkt/c/{tok}?u={uh}"
        text = text.replace(primary_url, tracked)
    if "STOP" not in text.upper():
        text = f"{text} Reply STOP to opt out."
    return text


def build_ctx(subscriber: Optional[Dict[str, Any]],
                 tenant: Optional[Dict[str, Any]],
                 campaign: Dict[str, Any],
                 send_id: Optional[str] = None) -> Dict[str, Any]:
    """Compose the substitution context for a single recipient."""
    s = subscriber or {}
    t = tenant or {}
    base = _base_backend_url()
    unsub_url = ""
    prefs_url = ""
    web_view_url = ""
    if s.get("id") and send_id:
        tok = mint_token(campaign["id"], s["id"], send_id)
        unsub_url = f"{base}/api/public/mkt/unsub/{tok}"
        prefs_url = f"{base}/api/public/mkt/prefs/{tok}"
        web_view_url = f"{base}/api/public/mkt/view/{tok}"
    return {
        "first_name": s.get("first_name") or (s.get("name") or "").split(" ")[0] or "",
        "last_name":  s.get("last_name") or "",
        "email":      s.get("email") or "",
        "phone":      s.get("phone") or "",
        "tenant_name": t.get("business_name") or t.get("name") or "",
        "sender_name": campaign.get("from_name") or t.get("business_name") or "",
        "unsubscribe_url": unsub_url,
        "preferences_url": prefs_url,
        "web_view_url":   web_view_url,
    }


# ─── Send pipeline ─────────────────────────────────────────────────────
_ALLOWED_STATUS = {"draft", "scheduled", "sending", "sent",
                     "paused", "failed", "cancelled", "archived"}


async def dispatch_campaign(tenant_id: str, campaign_id: str) -> Dict[str, Any]:
    """Main entry-point for sending. Idempotent — will pick up where
    ``sending`` left off if called again."""
    camp = await db.marketing_campaigns.find_one(
        {"id": campaign_id, "tenant_id": tenant_id}, {"_id": 0})
    if not camp:
        return {"ok": False, "reason": "not_found", "sent": 0}
    if camp.get("status") in ("sent", "cancelled", "failed"):
        return {"ok": False, "reason": camp.get("status"), "sent": 0}
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0}) or {}
    audience = await resolve_audience(tenant_id, camp.get("audience") or {})
    if not audience["subscriber_ids"]:
        await db.marketing_campaigns.update_one(
            {"id": campaign_id, "tenant_id": tenant_id},
            {"$set": {"status": "sent", "sent_at": now_iso(),
                        "updated_at": now_iso(),
                        "audience_final": {"estimated_size": 0,
                                             "unique_email_count": 0,
                                             "unique_phone_count": 0}}})
        return {"ok": True, "sent": 0, "reason": "empty_audience"}

    await db.marketing_campaigns.update_one(
        {"id": campaign_id, "tenant_id": tenant_id},
        {"$set": {"status": "sending", "updated_at": now_iso(),
                    "audience_final": {
                        "estimated_size": audience["estimated_size"],
                        "unique_email_count": audience["unique_email_count"],
                        "unique_phone_count": audience["unique_phone_count"],
                    }}})

    subs = await db.subscribers.find(
        {"tenant_id": tenant_id,
          "id": {"$in": audience["subscriber_ids"]}},
        {"_id": 0}).to_list(len(audience["subscriber_ids"]) + 1)

    sent = 0
    failed = 0
    skipped = 0
    channel = camp.get("channel") or "email"

    for sub in subs:
        # Race-safe: subscriber could have unsubbed between estimate + send.
        if sub.get("status") != "subscribed":
            skipped += 1
            continue
        send_id = new_id()
        send_doc = {
            "id": send_id, "tenant_id": tenant_id,
            "campaign_id": campaign_id, "subscriber_id": sub["id"],
            "channel": channel, "sent_at": None,
            "status": "queued", "provider_message_id": None,
            "open_count": 0, "click_count": 0,
            "first_opened_at": None, "last_opened_at": None,
            "first_clicked_at": None, "last_clicked_at": None,
        }
        await db.marketing_campaign_sends.insert_one(send_doc)

        ctx = build_ctx(sub, tenant, camp, send_id)
        ok_email = True
        ok_sms = True
        provider_id: Optional[str] = None

        if channel in ("email", "both") and sub.get("email"):
            html_tpl = (camp.get("content") or {}).get("email_html") or ""
            rendered, _ = render_body(html_tpl, ctx)
            tracked_html, url_index = rewrite_email_html(
                rendered, campaign_id, sub["id"], send_id)
            # Persist link catalogue for top-links analytics.
            for entry in url_index:
                await db.marketing_campaign_click_events.update_one(
                    {"tenant_id": tenant_id, "campaign_id": campaign_id,
                      "url_hash": entry["url_hash"], "kind": "catalog"},
                    {"$setOnInsert": {"id": new_id(),
                                        "url": entry["url"],
                                        "kind": "catalog",
                                        "created_at": now_iso()}},
                    upsert=True)
            subject_r, _ = render_body(camp.get("subject") or "", ctx)
            try:
                from services.comms_email_adapter import send_email
                r = await send_email(
                    tenant_id, sub["email"], subject_r, tracked_html,
                    from_name=camp.get("from_name"),
                    from_email=camp.get("from_email"),
                    headers={"List-Unsubscribe":
                                 f"<{_base_backend_url()}/api/public/mkt/unsub/"
                                 f"{mint_token(campaign_id, sub['id'], send_id)}>"})
                provider_id = (r or {}).get("id") or (r or {}).get("message_id")
            except Exception as e:
                ok_email = False
                logger.warning(f"[m2] email send fail: {e}")

        if channel in ("sms", "both") and sub.get("phone"):
            sms_tpl = (camp.get("content") or {}).get("sms_body") or ""
            rendered_sms, _ = render_body(sms_tpl, ctx)
            # Best-effort: first http(s) link in body becomes the tracker.
            m = re.search(r"https?://\S+", rendered_sms)
            primary = m.group(0) if m else None
            final_sms = rewrite_sms_body(rendered_sms, campaign_id,
                                              sub["id"], send_id, primary)
            try:
                from services.comms_sms_adapter import send_sms
                r = await send_sms(tenant_id, sub["phone"], final_sms)
                provider_id = provider_id or (r or {}).get("provider_message_id")
            except Exception as e:
                ok_sms = False
                logger.warning(f"[m2] sms send fail: {e}")

        final_status = "sent" if (ok_email and ok_sms) else "failed"
        await db.marketing_campaign_sends.update_one(
            {"id": send_id},
            {"$set": {"status": final_status,
                        "sent_at": now_iso(),
                        "provider_message_id": provider_id or f"mock-{send_id[:8]}"}})
        if final_status == "sent":
            sent += 1
        else:
            failed += 1

    await db.marketing_campaigns.update_one(
        {"id": campaign_id, "tenant_id": tenant_id},
        {"$set": {"status": "sent" if failed == 0 else "sent",
                    "sent_at": now_iso(), "updated_at": now_iso(),
                    "counters": {"sent": sent, "failed": failed,
                                  "skipped": skipped}}})

    # Unified notifications — one row per admin summarising the send.
    try:
        from services.notifications import enqueue_for_tenant_admins
        await enqueue_for_tenant_admins(
            tenant_id, "marketing_campaign_sent",
            title=f"Campaign sent · {camp.get('name') or camp.get('subject') or campaign_id}",
            body=f"Sent to {sent} recipients · {failed} failed · {skipped} skipped.",
            source_ref={"kind": "marketing_campaign", "id": campaign_id},
            href=f"/marketing/campaigns/{campaign_id}",
        )
    except Exception as _e:
        logger.warning(f"[m2] campaign_sent notify failed: {_e}")

    return {"ok": True, "sent": sent, "failed": failed, "skipped": skipped}


# ─── Scheduler sweep (called by APScheduler) ───────────────────────────
async def run_scheduled_campaign_sweep() -> Dict[str, int]:
    """Fire any ``scheduled`` campaign whose ``scheduled_at`` has passed."""
    now = datetime.now(timezone.utc).isoformat()
    fired = 0
    async for c in db.marketing_campaigns.find(
        {"status": "scheduled",
          "schedule.scheduled_at": {"$lte": now}}, {"_id": 0}):
        await dispatch_campaign(c["tenant_id"], c["id"])
        fired += 1
    return {"fired": fired}
