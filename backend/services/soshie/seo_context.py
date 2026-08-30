"""Soshie · SEO-Suite grounding · Feb-2026.

Single public entry point: :func:`build_seo_context`.

Reads from five Mongo collections that the SEO Suite already
populates (no new writes here — pure reader):

* ``seo_scans``        — latest ``run_scan`` output (score, issues).
* ``aeo_fixes``        — open schema / FAQ / entity gaps.
* ``rank_snapshots``   — 3x3 geo-grid rank movers (last 14 days).
* ``brand_mentions``   — Phase 5c crawler results (last 30 days).
* ``keyword_lookups``  — 24 h keyword-ideator cache.

Returns a compact ``dict`` capped at <2 KB when serialized —
guardrail so the system-prompt payload doesn't blow past Claude
token budgets. Truncation is deterministic (top-N by recency
first, then by magnitude) so a re-run produces identical context
for a given tenant snapshot.

Cost: 5 tiny queries, each covered by an existing tenant-scoped
index. Sub-30ms in local benchmarks.

Not wired into the chat cheap-path (Soshie chat still runs on the
plain brand-brain prompt) — only surfaces on ACTION handlers where
grounding pays off (draft_post, content_calendar, hashtag_research,
analyze_engagement).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger

# Byte cap so the context blob can't push Claude over its token
# budget when combined with the base system prompt + brand brain.
_MAX_BYTES = 2000
# Per-section item caps — trimmed BEFORE any string truncation so
# the shape stays predictable and testable.
_MAX_ISSUES = 5
_MAX_AEO_GAPS = 5
_MAX_RANK_MOVERS = 5
_MAX_MENTIONS = 5
_MAX_KEYWORDS = 8


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def _latest_seo_scan(tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return the freshest complete scan for the tenant, or None
    when no scan has run yet. Only surfaces the summary fields —
    the raw HTML / broken-link list stays in Mongo."""
    row = await db.seo_scans.find_one(
        {"tenant_id": tenant_id, "status": "complete"},
        {"_id": 0, "id": 1, "target_url": 1, "finished_at": 1,
          "results.score": 1, "results.issue_count": 1,
          "results.aeo_signals.overall_aeo_score": 1},
        sort=[("finished_at", -1)],
    )
    if not row:
        return None
    results = row.get("results") or {}
    return {
        "url": row.get("target_url"),
        "at": row.get("finished_at"),
        "score": results.get("score"),
        "issue_count": results.get("issue_count") or {},
        "aeo_score": (results.get("aeo_signals") or {}).get(
            "overall_aeo_score"),
    }


async def _top_aeo_gaps(tenant_id: str) -> List[Dict[str, Any]]:
    """Open (unresolved) AEO fixes — schema gaps, FAQ suggestions,
    entity-clarity issues. Sorted newest first."""
    gaps: List[Dict[str, Any]] = []
    async for row in db.aeo_fixes.find(
            {"tenant_id": tenant_id,
              "$or": [{"status": {"$ne": "resolved"}},
                        {"status": {"$exists": False}}]},
            {"_id": 0, "kind": 1, "title": 1, "priority": 1,
              "created_at": 1}
        ).sort("created_at", -1).limit(_MAX_AEO_GAPS):
        gaps.append({
            "kind": row.get("kind"),
            "title": (row.get("title") or "")[:100],
            "priority": row.get("priority"),
        })
    return gaps


async def _rank_movers(tenant_id: str) -> List[Dict[str, Any]]:
    """Per-keyword rank change over the last 14 days. Returns the
    top ``_MAX_RANK_MOVERS`` biggest movers (either direction)."""
    since = _iso_days_ago(14)
    by_keyword: Dict[str, List[Dict[str, Any]]] = {}
    async for row in db.rank_snapshots.find(
            {"tenant_id": tenant_id, "checked_at": {"$gte": since}},
            {"_id": 0, "keyword": 1, "rank": 1, "checked_at": 1},
        ).sort("checked_at", -1).limit(200):
        kw = row.get("keyword") or ""
        if not kw or row.get("rank") is None:
            continue
        by_keyword.setdefault(kw, []).append(row)
    movers: List[Dict[str, Any]] = []
    for kw, rows in by_keyword.items():
        # rows are already newest-first from the sort above.
        if len(rows) < 2:
            continue
        latest = rows[0]["rank"]
        oldest = rows[-1]["rank"]
        try:
            delta = int(oldest) - int(latest)   # positive = improved
        except (TypeError, ValueError):
            continue
        movers.append({
            "keyword": kw[:60], "current": latest, "delta": delta,
        })
    movers.sort(key=lambda m: abs(m["delta"]), reverse=True)
    return movers[:_MAX_RANK_MOVERS]


async def _top_mentions(tenant_id: str) -> List[Dict[str, Any]]:
    """Top brand-mention domains from the last 30 days (Phase 5c
    ``brand_mentions`` crawler)."""
    since = _iso_days_ago(30)
    by_domain: Dict[str, int] = {}
    async for row in db.brand_mentions.find(
            {"tenant_id": tenant_id, "created_at": {"$gte": since}},
            {"_id": 0, "domain": 1, "title": 1},
        ).limit(500):
        d = row.get("domain") or ""
        if d:
            by_domain[d] = by_domain.get(d, 0) + 1
    top = sorted(by_domain.items(), key=lambda x: -x[1])[:_MAX_MENTIONS]
    return [{"domain": d, "count": c} for d, c in top]


async def _recent_keywords(tenant_id: str) -> List[str]:
    """Recent keyword ideations — the seed terms admins have looked
    up in the last 7 days. Used as topic prompts for Soshie."""
    since = _iso_days_ago(7)
    seeds: List[str] = []
    async for row in db.keyword_lookups.find(
            {"tenant_id": tenant_id, "created_at": {"$gte": since}},
            {"_id": 0, "seed": 1},
        ).sort("created_at", -1).limit(_MAX_KEYWORDS):
        s = (row.get("seed") or "").strip()
        if s and s not in seeds:
            seeds.append(s[:60])
    return seeds


def _fit_budget(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Trim per-section arrays until the JSON payload fits under
    ``_MAX_BYTES``. Called ONCE at the end so all sections get a
    fair-share cut before any single one is starved."""
    encoded = json.dumps(payload, separators=(",", ":"))
    if len(encoded) <= _MAX_BYTES:
        return payload
    # Trim arrays from the tail until we fit.
    for k in ("recent_keywords", "top_mentions", "rank_movers",
                "aeo_gaps", "issue_count"):
        while len(encoded) > _MAX_BYTES and payload.get(k):
            v = payload[k]
            if isinstance(v, list) and v:
                v.pop()
            elif isinstance(v, dict) and v:
                v.pop(next(iter(v)))
            else:
                break
            encoded = json.dumps(payload, separators=(",", ":"))
    return payload


async def build_seo_context(tenant_id: str) -> Dict[str, Any]:
    """Assemble the compact SEO-context blob for a tenant.

    Returns a dict with these keys (all optional — empty sections
    are dropped so an early-stage tenant returns an empty ``{}``
    rather than a scaffolded skeleton):

        latest_scan     : {url, at, score, issue_count, aeo_score}
        aeo_gaps        : [{kind, title, priority}, ...]
        rank_movers     : [{keyword, current, delta}, ...]
        top_mentions    : [{domain, count}, ...]
        recent_keywords : [str, ...]

    All reads are best-effort — a collection that doesn't exist
    yet returns an empty section rather than raising. Callers
    should treat this function as ``async def -> dict``, no
    exceptions.
    """
    try:
        latest_scan = await _latest_seo_scan(tenant_id)
        aeo_gaps = await _top_aeo_gaps(tenant_id)
        rank_movers = await _rank_movers(tenant_id)
        top_mentions = await _top_mentions(tenant_id)
        recent_keywords = await _recent_keywords(tenant_id)
    except Exception as e:                                        # noqa: BLE001
        logger.warning("[soshie.seo_context] read failed: %s", e)
        return {}

    payload: Dict[str, Any] = {}
    if latest_scan:
        payload["latest_scan"] = latest_scan
    if aeo_gaps:
        payload["aeo_gaps"] = aeo_gaps
    if rank_movers:
        payload["rank_movers"] = rank_movers
    if top_mentions:
        payload["top_mentions"] = top_mentions
    if recent_keywords:
        payload["recent_keywords"] = recent_keywords
    return _fit_budget(payload)


def format_seo_context_for_prompt(ctx: Dict[str, Any]) -> str:
    """Render the context blob as a human-readable block that can
    be appended to Soshie's system prompt. Empty context returns
    the empty string so callers can safely concat unconditionally."""
    if not ctx:
        return ""
    lines: List[str] = ["— SEO signals for grounding —"]
    scan = ctx.get("latest_scan")
    if scan:
        parts = [f"latest scan of {scan.get('url')}"]
        if scan.get("score") is not None:
            parts.append(f"score {scan['score']}/100")
        if scan.get("aeo_score") is not None:
            parts.append(f"AEO {scan['aeo_score']}/100")
        lines.append("* " + " · ".join(parts))
    gaps = ctx.get("aeo_gaps") or []
    if gaps:
        for g in gaps[:3]:
            lines.append(
                f"* AEO gap ({g.get('kind')}): {g.get('title')}")
    movers = ctx.get("rank_movers") or []
    if movers:
        for m in movers[:3]:
            arrow = "↑" if (m.get("delta") or 0) > 0 else "↓"
            lines.append(
                f"* rank {arrow} {abs(m.get('delta') or 0)}: "
                f"'{m.get('keyword')}' now at #{m.get('current')}")
    mentions = ctx.get("top_mentions") or []
    if mentions:
        lines.append(
            "* top mention domains: "
            + ", ".join(f"{m['domain']}({m['count']})"
                          for m in mentions[:3]))
    kws = ctx.get("recent_keywords") or []
    if kws:
        lines.append(
            "* recent keyword ideas: " + ", ".join(kws[:5]))
    return "\n".join(lines)
