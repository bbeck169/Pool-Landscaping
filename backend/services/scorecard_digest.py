"""Phase 7 · Feb-2026 — Weekly Scorecard Digest.

Aggregates per-department scorecards over Mon-Sun windows, computes
WoW deltas, renders a Slack Block Kit payload + Resend email HTML,
and persists to ``scorecard_digests``. Delivery functions accept
injected clients so tests never hit Slack or Resend.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from config import db, logger  # noqa: F401


# ── Period math ──────────────────────────────────────────────────
def last_completed_week(as_of: Optional[date] = None) -> Tuple[date, date]:
    """Return the (Monday, Sunday) of the last COMPLETED week."""
    today = as_of or date.today()
    # weekday(): Mon=0..Sun=6.
    days_since_sunday = (today.weekday() + 1) % 7
    last_sunday = today - timedelta(days=days_since_sunday)
    last_monday = last_sunday - timedelta(days=6)
    return last_monday, last_sunday


def prior_week(period_start: date, period_end: date) -> Tuple[date, date]:
    span = (period_end - period_start).days + 1
    return period_start - timedelta(days=span), period_start - timedelta(days=1)


def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _delta_pct(cur: float, prev: float) -> Optional[float]:
    """WoW delta. Divide-by-zero returns None (not crash)."""
    if prev is None or prev == 0:
        return None
    return round(((cur - prev) / prev) * 100.0, 1)


# ── Composite scoring helpers ────────────────────────────────────
def _norm(v: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return min(1.0, max(0.0, v / cap)) * 100.0


def _tech_composite(jobs: int, revenue: float, rating: Optional[float]) -> float:
    j = _norm(jobs, 20)          # 20 jobs/wk saturates
    r = _norm(revenue, 5000)     # $5k/wk saturates
    q = ((rating or 0) / 5.0) * 100.0
    return round(0.4 * j + 0.4 * r + 0.2 * q, 1)


def _dispatcher_composite(assignments: int, optimizations: int,
                             avg_savings_km: float) -> float:
    a = _norm(assignments, 25)
    o = _norm(optimizations, 15)
    s = _norm(avg_savings_km, 10)
    return round(0.4 * a + 0.3 * o + 0.3 * s, 1)


def _sales_composite(new_quotes: int, conversions: int,
                        value_converted: float) -> float:
    c = _norm(conversions, 10)
    v = _norm(value_converted, 20000)
    n = _norm(new_quotes, 15)
    return round(0.5 * c + 0.3 * v + 0.2 * n, 1)


# ── Aggregators ──────────────────────────────────────────────────
async def aggregate_field(tenant_id: str, start: date, end: date,
                             ) -> Dict[str, Dict[str, Any]]:
    """Return {user_id: {name, jobs, revenue, rating, composite}}."""
    lo = _iso(start); hi = _iso(end) + "T23:59:59"
    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"jobs": 0, "revenue": 0.0, "rating_sum": 0.0, "rating_n": 0})
    async for j in db.jobs.find({"tenant_id": tenant_id,
                                    "status": "completed",
                                    "scheduled_date": {"$gte": lo, "$lte": hi}},
                                   {"_id": 0, "id": 1, "tech_user_id": 1,
                                     "assigned_to": 1, "technician_id": 1,
                                     "technician_name": 1,
                                     "invoiced_amount": 1, "amount": 1}):
        tid = j.get("tech_user_id") or j.get("assigned_to") or j.get("technician_id")
        if not tid:
            continue
        buckets[tid]["jobs"] += 1
        buckets[tid]["revenue"] += float(j.get("invoiced_amount") or j.get("amount") or 0.0)
        buckets[tid]["name"] = j.get("technician_name") or ""
    # Ratings from public check-ins.
    try:
        async for c in db.public_checkins.find(
            {"tenant_id": tenant_id,
              "created_at": {"$gte": lo, "$lte": hi + "Z"},
              "rating": {"$exists": True, "$ne": None}},
            {"_id": 0, "tech_user_id": 1, "rating": 1}):
            tid = c.get("tech_user_id")
            if not tid or tid not in buckets:
                continue
            buckets[tid]["rating_sum"] += float(c["rating"])
            buckets[tid]["rating_n"] += 1
    except Exception:
        pass
    # Fill names from users collection.
    out: Dict[str, Dict[str, Any]] = {}
    for uid, b in buckets.items():
        if not b.get("name"):
            u = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1, "email": 1})
            b["name"] = (u or {}).get("name") or (u or {}).get("email") or uid
        rating = (b["rating_sum"] / b["rating_n"]) if b["rating_n"] else None
        out[uid] = {"user_id": uid, "name": b["name"],
                    "jobs": b["jobs"], "revenue": round(b["revenue"], 2),
                    "rating": round(rating, 2) if rating is not None else None,
                    "composite": _tech_composite(b["jobs"], b["revenue"], rating)}
    return out


async def aggregate_dispatch(tenant_id: str, start: date, end: date,
                                ) -> Dict[str, Dict[str, Any]]:
    lo = _iso(start); hi = _iso(end) + "T23:59:59"
    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"assignments": 0, "optimizations": 0,
                  "savings_sum_km": 0.0, "savings_n": 0})
    for coll, key in [(db.audit_log, "type")]:
        try:
            async for row in coll.find({"tenant_id": tenant_id,
                                          "ts": {"$gte": lo + "T00:00:00",
                                                  "$lte": hi}},
                                         {"_id": 0}):
                uid = row.get("user_id") or row.get("actor_id") or ""
                ev = row.get(key) or ""
                if not uid:
                    continue
                if ev == "dispatch.route.apply":
                    buckets[uid]["optimizations"] += 1
                    sv = float(row.get("meta", {}).get("savings_km") or 0)
                    if sv:
                        buckets[uid]["savings_sum_km"] += sv
                        buckets[uid]["savings_n"] += 1
                elif ev == "dispatch.route.insert":
                    buckets[uid]["assignments"] += 1
        except Exception:
            continue
    out: Dict[str, Dict[str, Any]] = {}
    for uid, b in buckets.items():
        u = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1, "email": 1})
        avg_km = (b["savings_sum_km"] / b["savings_n"]) if b["savings_n"] else 0.0
        out[uid] = {"user_id": uid,
                    "name": (u or {}).get("name") or (u or {}).get("email") or uid,
                    "assignments": b["assignments"],
                    "optimizations": b["optimizations"],
                    "avg_savings_km": round(avg_km, 2),
                    "composite": _dispatcher_composite(
                        b["assignments"], b["optimizations"], avg_km)}
    return out


async def aggregate_sales(tenant_id: str, start: date, end: date,
                             ) -> Dict[str, Dict[str, Any]]:
    lo = _iso(start); hi = _iso(end) + "T23:59:59"
    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"new_quotes": 0, "conversions": 0, "value_converted": 0.0})
    async for q in db.quotes.find({"tenant_id": tenant_id,
                                      "created_at": {"$gte": lo + "T00:00:00",
                                                      "$lte": hi + "Z"}},
                                     {"_id": 0}):
        uid = q.get("created_by") or q.get("owner_id") or q.get("sales_user_id")
        if not uid:
            continue
        buckets[uid]["new_quotes"] += 1
        if (q.get("doc_type") == "invoice" or q.get("converted_at")):
            buckets[uid]["conversions"] += 1
            buckets[uid]["value_converted"] += float(q.get("total") or 0.0)
    out: Dict[str, Dict[str, Any]] = {}
    for uid, b in buckets.items():
        u = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1, "email": 1, "role": 1})
        if not u or (u.get("role") or "") not in {"sales", "owner", "admin", "super_admin"}:
            continue
        out[uid] = {"user_id": uid,
                    "name": u.get("name") or u.get("email") or uid,
                    "new_quotes": b["new_quotes"],
                    "conversions": b["conversions"],
                    "value_converted": round(b["value_converted"], 2),
                    "composite": _sales_composite(b["new_quotes"],
                                                     b["conversions"],
                                                     b["value_converted"])}
    return out


def _top_bottom(rows: Dict[str, Dict[str, Any]], prior: Dict[str, Dict[str, Any]],
                 n: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    lst = list(rows.values())
    for r in lst:
        prev = prior.get(r["user_id"], {}).get("composite")
        r["delta_pct"] = _delta_pct(r["composite"], prev)
    lst.sort(key=lambda r: r["composite"], reverse=True)
    return {"top": lst[:n], "bottom": list(reversed(lst[-n:])) if len(lst) > n else []}


AGGREGATORS = {"field": aggregate_field,
                 "dispatch": aggregate_dispatch,
                 "sales": aggregate_sales}


async def compute_digest(tenant: Dict[str, Any],
                            period_end: Optional[date] = None,
                            ) -> Dict[str, Any]:
    tenant_id = tenant.get("id") or tenant.get("tenant_id")
    if period_end is None:
        _, period_end = last_completed_week()
    period_start = period_end - timedelta(days=6)
    prior_start, prior_end = prior_week(period_start, period_end)
    departments: Dict[str, Dict[str, Any]] = {}
    for dept, fn in AGGREGATORS.items():
        cur = await fn(tenant_id, period_start, period_end)
        if not cur:
            continue
        prev = await fn(tenant_id, prior_start, prior_end)
        departments[dept] = _top_bottom(cur, prev)
    return {"tenant_id": tenant_id,
            "period_start": _iso(period_start),
            "period_end": _iso(period_end),
            "prior_period_start": _iso(prior_start),
            "prior_period_end": _iso(prior_end),
            "departments": departments,
            "generated_at": datetime.now(timezone.utc).isoformat()}


# ── Slack + Email builders ───────────────────────────────────────
DEPT_LABEL = {"field": "Field Techs", "dispatch": "Dispatchers",
                "sales": "Sales"}
MEDAL = ["🥇", "🥈", "🥉"]


def _delta_arrow(pct: Optional[float]) -> str:
    if pct is None:
        return "—"
    if pct >= 0:
        return f"↑ {pct}%"
    return f"↓ {abs(pct)}%"


def build_slack_blocks(tenant_name: str, digest: Dict[str, Any]) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = []
    blocks.append({"type": "header", "text": {"type": "plain_text",
        "text": f"📊 Weekly Scorecard · {tenant_name} · "
                 f"{digest['period_start']} – {digest['period_end']}"}})
    for dept, data in digest.get("departments", {}).items():
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"*{DEPT_LABEL.get(dept, dept.title())}*"}})
        if data.get("top"):
            lines = [f"{MEDAL[i] if i < 3 else '•'} *{r['name']}* — {r['composite']} · "
                       f"{_delta_arrow(r.get('delta_pct'))}"
                       for i, r in enumerate(data["top"])]
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": "Top:\n" + "\n".join(lines)}})
        if data.get("bottom"):
            lines = [f"• *{r['name']}* — {r['composite']} · "
                       f"{_delta_arrow(r.get('delta_pct'))}"
                       for r in data["bottom"]]
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": "Bottom:\n" + "\n".join(lines)}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
        "text": f"Generated {digest['generated_at']}"}]})
    return {"blocks": blocks}


def build_email_html(tenant_name: str, digest: Dict[str, Any],
                        brand_color: str = "#0284C7") -> Tuple[str, str, str]:
    subject = f"Weekly Scorecard · {tenant_name} · Week of {digest['period_start']}"
    rows_html: List[str] = []
    plain_lines: List[str] = [f"Weekly Scorecard · {tenant_name}",
                                 f"Week: {digest['period_start']} – {digest['period_end']}",
                                 ""]
    for dept, data in digest.get("departments", {}).items():
        rows_html.append(
            f'<h3 style="color:{brand_color};margin-bottom:4px">'
            f"{DEPT_LABEL.get(dept, dept.title())}</h3>")
        plain_lines.append(DEPT_LABEL.get(dept, dept.title()))
        for label, entries in (("Top", data.get("top") or []),
                                 ("Bottom", data.get("bottom") or [])):
            if not entries:
                continue
            rows_html.append(f"<p style='margin:6px 0 2px'><b>{label}</b></p><ul>")
            plain_lines.append(f"  {label}:")
            for i, r in enumerate(entries):
                medal = MEDAL[i] if label == "Top" and i < 3 else "•"
                rows_html.append(
                    f"<li>{medal} <b>{r['name']}</b> — {r['composite']} "
                    f"<span style='color:#64748B'>({_delta_arrow(r.get('delta_pct'))})</span></li>")
                plain_lines.append(
                    f"    {medal} {r['name']} — {r['composite']} ({_delta_arrow(r.get('delta_pct'))})")
            rows_html.append("</ul>")
        plain_lines.append("")
    html = (
        f"<div style='font-family:ui-sans-serif,system-ui;padding:16px;color:#0F172A'>"
        f"<h1 style='color:{brand_color};font-size:20px'>Weekly Scorecard</h1>"
        f"<p><b>{tenant_name}</b> · {digest['period_start']} – {digest['period_end']}</p>"
        + "".join(rows_html) +
        f"<p style='color:#94A3B8;font-size:11px;margin-top:24px'>"
        f"Generated {digest['generated_at']}</p></div>")
    return subject, html, "\n".join(plain_lines)


# ── Delivery adapters (injectable for tests) ─────────────────────
async def _default_slack_post(webhook_url: str,
                                  payload: Dict[str, Any]) -> Dict[str, Any]:
    import httpx
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(webhook_url, json=payload, timeout=10)
        return {"ok": 200 <= r.status_code < 300, "status": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}


async def _default_resend_send(to_list: List[str], subject: str,
                                   html: str, text: str) -> Dict[str, Any]:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return {"ok": False, "error": "resend_not_configured"}
    import httpx
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post("https://api.resend.com/emails",
                                 headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"},
                                 json={"from": os.environ.get("RESEND_FROM_EMAIL",
                                                                 "no-reply@example.com"),
                                        "to": to_list, "subject": subject,
                                        "html": html, "text": text}, timeout=15)
        return {"ok": 200 <= r.status_code < 300, "status": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}


async def deliver_digest(*, tenant: Dict[str, Any], digest: Dict[str, Any],
                            settings: Dict[str, Any], channels: List[str],
                            slack_post=_default_slack_post,
                            resend_send=_default_resend_send,
                            ) -> Dict[str, Any]:
    tenant_name = tenant.get("name") or tenant.get("business_name") or "Business"
    result: Dict[str, Any] = {"slack": {"sent": False}, "email": {"sent": False}}
    if "slack" in channels and settings.get("slack_webhook_url"):
        payload = build_slack_blocks(tenant_name, digest)
        r = await slack_post(settings["slack_webhook_url"], payload)
        result["slack"] = {"sent": bool(r.get("ok")),
                            "channel": settings.get("slack_channel"),
                            "error": r.get("error")}
    if "email" in channels and (settings.get("recipient_emails") or []):
        subject, html, text = build_email_html(tenant_name, digest,
            brand_color=(tenant.get("brand_color") or "#0284C7"))
        r = await resend_send(settings["recipient_emails"], subject, html, text)
        result["email"] = {"sent": bool(r.get("ok")),
                            "recipients": settings["recipient_emails"],
                            "error": r.get("error")}
    return result


# ── Persistence + cron ───────────────────────────────────────────
async def get_settings(tenant_id: str) -> Dict[str, Any]:
    s = await db.scorecard_digest_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}) or {}
    return {"tenant_id": tenant_id,
            "slack_webhook_url": s.get("slack_webhook_url") or "",
            "slack_channel": s.get("slack_channel") or "",
            "recipient_emails": s.get("recipient_emails") or [],
            "enabled": bool(s.get("enabled")),
            "day_of_week": int(s.get("day_of_week") or 1),
            "hour_utc": int(s.get("hour_utc") or 14)}


def _mask_webhook(url: str) -> str:
    if not url: return ""
    if len(url) <= 12: return "***"
    return f"…{url[-6:]}"


async def public_settings(tenant_id: str) -> Dict[str, Any]:
    s = await get_settings(tenant_id)
    s["slack_webhook_url_masked"] = _mask_webhook(s["slack_webhook_url"])
    s.pop("slack_webhook_url", None)
    return s


async def save_settings(tenant_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    current = await get_settings(tenant_id)
    for k in ("slack_webhook_url", "slack_channel", "recipient_emails",
               "enabled", "day_of_week", "hour_utc"):
        if k in patch and patch[k] is not None:
            current[k] = patch[k]
    await db.scorecard_digest_settings.update_one(
        {"tenant_id": tenant_id}, {"$set": current}, upsert=True)
    return await public_settings(tenant_id)


async def already_generated_this_week(tenant_id: str,
                                          period_start: date) -> bool:
    return bool(await db.scorecard_digests.find_one(
        {"tenant_id": tenant_id, "period_start": _iso(period_start)},
        {"_id": 0, "digest_id": 1}))


async def weekly_digest_cron() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour
    ran = 0
    async for s in db.scorecard_digest_settings.find(
        {"enabled": True, "day_of_week": weekday, "hour_utc": hour},
        {"_id": 0}):
        tenant = await db.tenants.find_one({"id": s["tenant_id"]}, {"_id": 0}) or {}
        if not tenant:
            continue
        tenant = {"id": s["tenant_id"], **tenant}
        period_start, period_end = last_completed_week()
        if await already_generated_this_week(s["tenant_id"], period_start):
            continue
        try:
            digest = await compute_digest(tenant, period_end=period_end)
            digest["digest_id"] = f"dgst_{s['tenant_id'][:8]}_{_iso(period_start)}"
            settings = await get_settings(s["tenant_id"])
            delivery = await deliver_digest(tenant=tenant, digest=digest,
                                                settings=settings,
                                                channels=["slack", "email"])
            digest["delivery"] = delivery
            digest["generated_by"] = "cron"
            await db.scorecard_digests.insert_one({**digest})
            ran += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[scorecard] tenant {s['tenant_id']} failed: {e}")
            continue
    return {"tenants_run": ran}
