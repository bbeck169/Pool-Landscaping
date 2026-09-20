"""Phase 8 · Feb-2026 — Weekly AEO PDF Digest.

Aggregates the tenant's AEO health (Auditor score, AI Visibility,
Brand Mentions, Action Items) for the last completed week and renders
a lightweight ReportLab PDF (< 500 KB). Delivered via Resend as an
attachment. Injectable Resend/uploader for tests.
"""
from __future__ import annotations

import io
import os
import uuid
from base64 import b64encode
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from config import db, logger  # noqa: F401
from services.scorecard_digest import last_completed_week, _iso, _delta_pct

# Reuse Phase 7's Resend stub for consistency.
from services.scorecard_digest import _default_resend_send  # noqa: F401


# ── Metric aggregation ───────────────────────────────────────────
async def _aeo_score_and_delta(tenant_id: str, start: date,
                                  end: date) -> Dict[str, Any]:
    lo = _iso(start); hi = _iso(end) + "T23:59:59"
    prev_lo = _iso(start - timedelta(days=7)); prev_hi = _iso(start - timedelta(days=1)) + "T23:59:59"
    latest = await db.seo_scans.find_one(
        {"tenant_id": tenant_id, "status": "complete",
          "created_at": {"$gte": lo, "$lte": hi}},
        {"_id": 0, "results": 1}, sort=[("created_at", -1)])
    prior = await db.seo_scans.find_one(
        {"tenant_id": tenant_id, "status": "complete",
          "created_at": {"$gte": prev_lo, "$lte": prev_hi}},
        {"_id": 0, "results": 1}, sort=[("created_at", -1)])
    def _pick(s):
        return (((s or {}).get("results") or {}).get("aeo_signals") or {})
    cur = _pick(latest); prev = _pick(prior)
    return {"current": int((cur.get("overall_aeo_score") or 0)),
            "prior": int(prev.get("overall_aeo_score") or 0) if prev else None,
            "delta_pct": _delta_pct(cur.get("overall_aeo_score") or 0,
                                       prev.get("overall_aeo_score") if prev else None),
            "sub_signals": {k: (cur.get(k) or {}).get("score", 0)
                             for k in ("schema", "faq", "llms_txt",
                                        "passages", "entity_clarity")}}


async def _visibility_stats(tenant_id: str, start: date,
                                end: date) -> Dict[str, Any]:
    lo = _iso(start); hi = _iso(end) + "T23:59:59"
    scores: List[int] = []; mentions = 0
    per_query: Dict[str, List[int]] = defaultdict(list)
    per_prov: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"probes": 0, "score_sum": 0, "mentions": 0})
    async for p in db.aeo_visibility_probes.find(
        {"tenant_id": tenant_id, "ran_at": {"$gte": lo, "$lte": hi}},
        {"_id": 0}):
        s = int(p.get("score") or 0)
        scores.append(s)
        if p.get("brand_mentioned"):
            mentions += 1
        per_query[p.get("query_template") or "?"].append(s)
        prov = p.get("llm_provider") or "?"
        per_prov[prov]["probes"] += 1
        per_prov[prov]["score_sum"] += s
        per_prov[prov]["mentions"] += 1 if p.get("brand_mentioned") else 0
    def _avg(v): return round(sum(v)/len(v), 1) if v else 0
    q_sorted = sorted(per_query.items(), key=lambda kv: _avg(kv[1]))
    return {"total_probes": len(scores),
            "avg_score": _avg(scores),
            "brand_mention_rate": round(mentions / len(scores) * 100.0, 1) if scores else 0.0,
            "winning_query": (q_sorted[-1][0] if q_sorted else None),
            "losing_query":  (q_sorted[0][0] if q_sorted else None),
            "providers": [{"provider": k, "probes": v["probes"],
                            "avg_score": round(v["score_sum"] / v["probes"], 1) if v["probes"] else 0,
                            "mention_rate": round(v["mentions"] / v["probes"] * 100, 1) if v["probes"] else 0}
                            for k, v in per_prov.items()]}


async def _mentions_stats(tenant_id: str, start: date, end: date,
                             include_negative_snippets: bool = True,
                             ) -> Dict[str, Any]:
    lo = _iso(start); hi = _iso(end) + "T23:59:59"
    total = 0
    sentiment = Counter()
    domains = Counter()
    negatives: List[Dict[str, Any]] = []
    async for m in db.brand_mentions.find(
        {"tenant_id": tenant_id,
          "discovered_at": {"$gte": lo, "$lte": hi}},
        {"_id": 0}):
        total += 1
        s = (m.get("sentiment") or "unknown")
        sentiment[s] += 1
        domains[m.get("domain") or "?"] += 1
        if include_negative_snippets and s == "negative" and len(negatives) < 3:
            negatives.append({"domain": m.get("domain"),
                                "title": (m.get("title") or "")[:80],
                                "snippet": (m.get("snippet") or "")[:120]})
    return {"total_new": total, "sentiment": dict(sentiment),
            "top_domains": [{"domain": d, "count": c}
                              for d, c in domains.most_common(5)],
            "negative_samples": negatives}


async def _action_items(tenant_id: str) -> Dict[str, Any]:
    pending_fixes = await db.aeo_fixes.count_documents(
        {"tenant_id": tenant_id, "applied": False,
          "superseded": {"$in": [False, None]}})
    pending_drafts = await db.mention_response_drafts.count_documents(
        {"tenant_id": tenant_id, "status": {"$in": ["draft", "copied"]}})
    return {"pending_fixes": pending_fixes,
            "pending_drafts": pending_drafts}


async def build_snapshot(tenant: Dict[str, Any],
                            period_end: Optional[date] = None,
                            include_negative_snippets: bool = True,
                            ) -> Dict[str, Any]:
    if period_end is None:
        _, period_end = last_completed_week()
    period_start = period_end - timedelta(days=6)
    tid = tenant.get("id") or tenant.get("tenant_id")
    return {
        "tenant_id": tid,
        "tenant_name": tenant.get("name") or tenant.get("business_name") or "Business",
        "period_start": _iso(period_start),
        "period_end": _iso(period_end),
        "aeo_score": await _aeo_score_and_delta(tid, period_start, period_end),
        "ai_visibility": await _visibility_stats(tid, period_start, period_end),
        "brand_mentions": await _mentions_stats(
            tid, period_start, period_end, include_negative_snippets),
        "action_items": await _action_items(tid),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── PDF renderer (ReportLab) ─────────────────────────────────────
def _bar(canvas, x, y, w, h, pct, label, color):
    canvas.setFillColor(color)
    canvas.rect(x, y, w * (max(0, min(100, pct)) / 100.0), h,
                 stroke=0, fill=1)
    canvas.setFillColorRGB(0.2, 0.2, 0.2)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(x, y + h + 2, f"{label} · {pct}")


def render_pdf(snapshot: Dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    W, H = LETTER
    x = 54; y = H - 60
    brand = HexColor("#0284C7")
    # Header.
    c.setFillColor(brand); c.setFont("Helvetica-Bold", 18)
    c.drawString(x, y, "Weekly AEO Digest")
    c.setFillColorRGB(0.3, 0.3, 0.3); c.setFont("Helvetica", 10)
    c.drawString(x, y - 16,
        f"{snapshot['tenant_name']}  ·  {snapshot['period_start']} – {snapshot['period_end']}")
    y -= 40

    def hr():
        nonlocal y
        c.setStrokeColorRGB(0.85, 0.85, 0.85); c.line(x, y, W - x, y); y -= 12

    def section(title):
        nonlocal y
        c.setFillColor(brand); c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, title); y -= 16
        c.setFillColorRGB(0.1, 0.1, 0.1); c.setFont("Helvetica", 9)

    def line(text):
        nonlocal y
        c.drawString(x, y, text[:110]); y -= 12

    # Section 1 — AEO score
    section("1. AEO Score Trend")
    s = snapshot["aeo_score"]
    delta = "—" if s["delta_pct"] is None else f"{'↑' if s['delta_pct'] >= 0 else '↓'} {abs(s['delta_pct'])}%"
    line(f"Current: {s['current']} / 100    ·    WoW: {delta}")
    for k, v in (s.get("sub_signals") or {}).items():
        _bar(c, x, y - 6, W - 2 * x - 40, 6, v, k, brand); y -= 22
    hr()

    # Section 2 — AI Visibility
    section("2. AI Visibility")
    v = snapshot["ai_visibility"]
    line(f"Total probes: {v['total_probes']}    Avg score: {v['avg_score']}    Mention rate: {v['brand_mention_rate']}%")
    line(f"Winning query: {v['winning_query'] or 'n/a'}")
    line(f"Losing query:  {v['losing_query'] or 'n/a'}")
    if v["providers"]:
        line("Providers:")
        for p in v["providers"]:
            line(f"  · {p['provider']}: probes={p['probes']} avg={p['avg_score']} mention_rate={p['mention_rate']}%")
    hr()

    # Section 3 — Brand Mentions
    section("3. Brand Mentions")
    m = snapshot["brand_mentions"]
    line(f"Total new: {m['total_new']}")
    line("Sentiment: " + ", ".join(f"{k}:{v}" for k, v in m['sentiment'].items()) if m['sentiment'] else "Sentiment: —")
    if m["top_domains"]:
        line("Top domains: " + ", ".join(f"{d['domain']}({d['count']})" for d in m["top_domains"]))
    for neg in m.get("negative_samples") or []:
        line(f"  ! {neg['domain']}: {neg['snippet']}")
    hr()

    # Section 4 — Action Items
    section("4. Action Items")
    a = snapshot["action_items"]
    line(f"Pending AEO fixes: {a['pending_fixes']}    Pending response drafts: {a['pending_drafts']}")
    line("Log in to CRM → Marketing → AEO to act on these.")

    # Footer.
    c.setFillColorRGB(0.6, 0.6, 0.6); c.setFont("Helvetica", 8)
    c.drawString(x, 40, f"Generated {snapshot['generated_at']} · "
                          "Unsubscribe by disabling in CRM Settings → Weekly AEO Digest.")
    c.showPage(); c.save()
    return buf.getvalue()


# ── Storage + signed URL ─────────────────────────────────────────
async def _store_pdf(tenant_id: str, digest_id: str, data: bytes) -> str:
    """Persist to db.aeo_digest_pdfs with base64 body. Signed URL is
    served through GET /api/aeo/digest/pdf/{digest_id}?token=... which
    we implement in the router (short-lived HMAC token)."""
    await db.aeo_digest_pdfs.update_one(
        {"tenant_id": tenant_id, "digest_id": digest_id},
        {"$set": {"tenant_id": tenant_id, "digest_id": digest_id,
                    "body_b64": b64encode(data).decode("ascii"),
                    "size_bytes": len(data),
                    "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True)
    return f"aeo_digest_pdfs/{tenant_id}/{digest_id}.pdf"


def sign_pdf_url(tenant_id: str, digest_id: str, ttl_sec: int = 600) -> str:
    """Return a query-string-signed URL that GET /api/aeo/digest/pdf will
    validate. Uses SECRET_KEY from env; falls back to a static salt if
    unset (never in prod)."""
    import hmac, hashlib, time
    secret = (os.environ.get("SECRET_KEY")
                or os.environ.get("JWT_SECRET") or "aeo-digest-signing-salt").encode()
    exp = int(time.time() + ttl_sec)
    body = f"{tenant_id}:{digest_id}:{exp}".encode()
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()[:32]
    return f"/api/aeo/digest/pdf/{digest_id}?tid={tenant_id}&exp={exp}&sig={sig}"


def verify_pdf_signature(tenant_id: str, digest_id: str,
                            exp: int, sig: str) -> bool:
    import hmac, hashlib, time
    if int(time.time()) > int(exp):
        return False
    secret = (os.environ.get("SECRET_KEY")
                or os.environ.get("JWT_SECRET") or "aeo-digest-signing-salt").encode()
    body = f"{tenant_id}:{digest_id}:{exp}".encode()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(expected, sig)


# ── Settings ─────────────────────────────────────────────────────
async def get_settings(tenant_id: str) -> Dict[str, Any]:
    s = await db.aeo_digest_settings.find_one({"tenant_id": tenant_id},
                                                 {"_id": 0}) or {}
    return {"tenant_id": tenant_id,
            "enabled": bool(s.get("enabled")),
            "recipient_emails": s.get("recipient_emails") or [],
            "day_of_week": int(s.get("day_of_week") or 1),
            "hour_utc": int(s.get("hour_utc") or 15),
            "include_negative_snippets": bool(s.get("include_negative_snippets", True))}


async def save_settings(tenant_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    current = await get_settings(tenant_id)
    for k in ("enabled", "recipient_emails", "day_of_week", "hour_utc",
               "include_negative_snippets"):
        if k in patch and patch[k] is not None:
            current[k] = patch[k]
    await db.aeo_digest_settings.update_one({"tenant_id": tenant_id},
                                                {"$set": current}, upsert=True)
    return current


# ── Delivery (Resend attachment) ─────────────────────────────────
async def deliver_email(*, tenant_name: str, snapshot: Dict[str, Any],
                           pdf_bytes: bytes, recipients: List[str],
                           resend_send=None,
                           locale: str = "en") -> Dict[str, Any]:
    """Phase D6.2 · Feb-2026 — email subject + body sentences are
    resolved via the D6 i18n catalog. The PDF content itself stays
    English (ReportLab's default Helvetica font can't render all
    UTF-8 characters our es/fr copy needs; PDF font-swap is out of
    D6 scope). Data (scores, counts, tenant name) passes through
    untranslated."""
    from services.email_body_i18n import t_email_body
    if not recipients:
        return {"sent": False, "error": "no_recipients"}
    subject = t_email_body(
        locale, "email.aeo_digest.subject",
        tenant_name=tenant_name, period_start=snapshot['period_start'],
    )
    heading = t_email_body(
        locale, "email.aeo_digest.heading", tenant_name=tenant_name)
    aeo_line = t_email_body(
        locale, "email.aeo_digest.aeo_score_line",
        score=snapshot['aeo_score']['current'])
    vis_line = t_email_body(
        locale, "email.aeo_digest.visibility_line",
        avg=snapshot['ai_visibility']['avg_score'],
        rate=snapshot['ai_visibility']['brand_mention_rate'])
    mentions_line = t_email_body(
        locale, "email.aeo_digest.new_mentions_line",
        count=snapshot['brand_mentions']['total_new'])
    action_line = t_email_body(
        locale, "email.aeo_digest.action_items_line",
        fixes=snapshot['action_items']['pending_fixes'],
        drafts=snapshot['action_items']['pending_drafts'])
    pdf_line = t_email_body(locale, "email.aeo_digest.pdf_attached")
    html = (
        f"<h2>{heading}</h2>"
        f"<p>{snapshot['period_start']} – {snapshot['period_end']}</p>"
        f"<ul>"
        f"<li>{aeo_line}</li>"
        f"<li>{vis_line}</li>"
        f"<li>{mentions_line}</li>"
        f"<li>{action_line}</li>"
        f"</ul><p>{pdf_line}</p>")
    text = (f"{heading}\n"
            f"{snapshot['period_start']} – {snapshot['period_end']}\n"
            f"{aeo_line}\n"
            f"{mentions_line}\n")
    attachment = {"filename": f"aeo-digest-{snapshot['period_start']}.pdf",
                  "content_b64": b64encode(pdf_bytes).decode("ascii")}
    if resend_send is None:
        # Real path via Resend HTTP with attachment.
        key = os.environ.get("RESEND_API_KEY")
        if not key:
            return {"sent": False, "error": "resend_not_configured"}
        import httpx
        try:
            async with httpx.AsyncClient() as c:
                r = await c.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {key}",
                                "Content-Type": "application/json"},
                    json={"from": os.environ.get("RESEND_FROM_EMAIL",
                                                     "no-reply@example.com"),
                            "to": recipients, "subject": subject,
                            "html": html, "text": text,
                            "attachments": [{
                                "filename": attachment["filename"],
                                "content": attachment["content_b64"]}]}, timeout=20)
            return {"sent": 200 <= r.status_code < 300,
                    "status": r.status_code, "recipients": recipients}
        except Exception as e:  # noqa: BLE001
            return {"sent": False, "error": str(e)[:120]}
    r = await resend_send(recipients=recipients, subject=subject,
                             html=html, text=text, attachment=attachment)
    return {"sent": bool(r.get("ok")), "recipients": recipients,
            "error": r.get("error")}


# ── Runner + cron ────────────────────────────────────────────────
async def run_digest(tenant: Dict[str, Any], *, period_end: Optional[date] = None,
                        deliver: bool = True, persist: bool = True,
                        generated_by: str = "",
                        resend_send=None) -> Dict[str, Any]:
    settings = await get_settings(tenant["id"])
    snapshot = await build_snapshot(tenant, period_end,
        include_negative_snippets=settings.get("include_negative_snippets", True))
    pdf_bytes = render_pdf(snapshot)
    digest_id = f"aeo_dgst_{uuid.uuid4().hex[:12]}"
    if persist:
        await _store_pdf(tenant["id"], digest_id, pdf_bytes)
    delivery = {"email": {"sent": False}}
    if deliver:
        # Phase D6.2 · Feb-2026 — AEO digest email carries the PDF
        # attachment. Email copy localises off the tenant's
        # ``default_locale``; the PDF body itself stays English
        # (font-encoding limitation — see the deliver_email
        # docstring).
        from services.i18n.email_locale import resolve_email_locale
        _locale = resolve_email_locale(recipient=None, tenant=tenant)
        delivery["email"] = await deliver_email(
            tenant_name=snapshot["tenant_name"],
            snapshot=snapshot, pdf_bytes=pdf_bytes,
            recipients=settings.get("recipient_emails") or [],
            resend_send=resend_send, locale=_locale)
    if persist:
        run_doc = {"tenant_id": tenant["id"], "digest_id": digest_id,
                    "period_start": snapshot["period_start"],
                    "period_end": snapshot["period_end"],
                    "generated_at": snapshot["generated_at"],
                    "generated_by": generated_by,
                    "pdf_size_bytes": len(pdf_bytes),
                    "metrics_snapshot": {
                        "aeo_score": snapshot["aeo_score"]["current"],
                        "ai_visibility": snapshot["ai_visibility"]["avg_score"],
                        "brand_mentions": snapshot["brand_mentions"]["total_new"],
                        "action_items": snapshot["action_items"]},
                    "delivery": delivery}
        await db.aeo_digest_runs.insert_one({**run_doc})
    return {"digest_id": digest_id, "snapshot": snapshot,
            "pdf_size_bytes": len(pdf_bytes),
            "pdf_url": sign_pdf_url(tenant["id"], digest_id),
            "delivery": delivery}


async def already_generated_this_week(tenant_id: str, period_start: date) -> bool:
    return bool(await db.aeo_digest_runs.find_one(
        {"tenant_id": tenant_id, "period_start": _iso(period_start)},
        {"_id": 0, "digest_id": 1}))


async def weekly_digest_cron() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    wd = now.weekday(); hour = now.hour
    ran = 0
    async for s in db.aeo_digest_settings.find(
        {"enabled": True, "day_of_week": wd, "hour_utc": hour}, {"_id": 0}):
        t = await db.tenants.find_one({"id": s["tenant_id"],
                                          "aeo_visibility_enabled": True}, {"_id": 0})
        if not t:
            continue
        tenant = {"id": s["tenant_id"], **t}
        period_start, _ = last_completed_week()
        if await already_generated_this_week(s["tenant_id"], period_start):
            continue
        try:
            await run_digest(tenant, generated_by="cron")
            ran += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[aeo_digest] tenant {s['tenant_id']} failed: {e}")
    return {"tenants_run": ran}
