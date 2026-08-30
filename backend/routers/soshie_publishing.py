"""Feb-2026 · Soshie publishing router.

Public endpoints (all under ``/api``):

* ``GET  /soshie/platforms``       — status of every registered
                                       platform (green / red +
                                       pending-gate detail).
* ``POST /soshie/publish``         — fan-out publisher.  Accepts
                                       ``{action_id, platforms:
                                       [str, ...], content?}``.
                                       Returns per-platform
                                       results.  Idempotent via
                                       ``X-Idempotency-Key`` header.
* ``GET  /soshie/publish/history`` — recent publish attempts.

Design notes:

* No new UI required for this batch — the router mirrors the
  P2 ship's fan-out contract so the frontend can be built any
  time.
* The router NEVER swallows an adapter's ``NotImplementedError``
  or ``PublishError``; per-platform failures land in the response
  as ``{status: "failed", error: str}`` and MUST NOT block the
  other platforms in the same request (e.g. WordPress publishes
  fine even if Facebook is still stub'd).
* Idempotency reuses the Phase O4 pattern
  (``utils_idempotency.replay_or_reserve``) so a mobile retry with
  the same ``X-Idempotency-Key`` short-circuits to the cached
  response.
* Every publish attempt writes to ``db.audit_logs`` with
  ``event="soshie.publish"`` (matches the pattern established by
  the Feb-2026 customer_activation_events + customer.hard_delete
  events).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from services.social import PLATFORMS, get_adapter
from services.social.base import PublishError
from services.soshie.moderation import moderate
from utils import get_current_user, new_id, now_iso
from utils_idempotency import (
    _fingerprint,
    replay_or_reserve,
    store_response,
)


router = APIRouter()


class PublishIn(BaseModel):
    action_id: Optional[str] = Field(
        None,
        description=(
            "ID of an approved row in ``ai_employee_actions`` "
            "(preferred). When omitted the caller must pass "
            "``text`` directly."))
    platforms: List[str] = Field(
        default_factory=list,
        description=(
            "Platform keys to fan-out to (subset of "
            "PLATFORMS). Duplicates deduped preserving order."))
    text: Optional[str] = Field(
        None,
        description=(
            "Raw post body — used when ``action_id`` is None or "
            "the action row doesn't carry content."))
    title: Optional[str] = None
    link: Optional[str] = None
    status: str = Field(
        "draft",
        description=(
            "WordPress-only: 'draft' or 'publish'. Ignored by "
            "other adapters (they always publish immediately)."))


# ─── GET /soshie/platforms ───────────────────────────────────────────────
@router.get("/soshie/platforms")
async def list_platform_status(
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return the connect grid — one entry per registered platform
    with its credential status.  Powers the "Connect Facebook /
    LinkedIn / ..." UI grid."""
    out: List[Dict[str, Any]] = []
    for platform in PLATFORMS.keys():
        adapter = get_adapter(platform)
        if adapter is None:
            out.append({"platform": platform, "ok": False,
                          "detail": "adapter module missing",
                          "supports": []})
            continue
        try:
            status = await adapter.check_credentials(tenant["id"])
        except Exception as e:                                    # noqa: BLE001
            logger.warning(
                "[soshie.platforms] %s check_credentials raised: %s",
                platform, e)
            status = {"ok": False,
                        "detail": f"adapter error: {e}"}
        out.append({
            "platform": platform,
            "ok": bool(status.get("ok")),
            "detail": status.get("detail") or "",
            "supports": sorted(adapter.supported_content_types()),
        })
    return {"platforms": out}


# ─── POST /soshie/publish ────────────────────────────────────────────────
@router.post("/soshie/publish")
async def publish(body: PublishIn,
                     request: Request,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)) -> Dict[str, Any]:
    """Fan-out publish. See module docstring for the contract."""
    # Idempotency — cached response wins full fan-out.
    idem_body = body.dict()
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /soshie/publish", idem_body,
    )
    if cached is not None:
        return cached
    resp = await _do_publish_fanout(
        tenant_id=tenant["id"], user_id=user["id"], body=body,
    )
    if idem_key:
        await store_response(
            idem_key, "POST /soshie/publish",
            tenant["id"], resp, idem_body,
        )
    return resp


async def _do_publish_fanout(
    *,
    tenant_id: str,
    user_id: str,
    body: PublishIn,
) -> Dict[str, Any]:
    """Pure fan-out core.  Contains no HTTP or idempotency logic —
    callers wrap this with idempotency at whichever seam they own
    (``POST /soshie/publish`` uses the ``X-Idempotency-Key`` header;
    :func:`execute_publish_for_action` uses the action row id).
    """
    if not body.platforms:
        raise HTTPException(422, "platforms[] cannot be empty")

    # Preserve caller order + dedup.
    platforms: List[str] = []
    _seen = set()
    for p in body.platforms:
        p = (p or "").strip().lower()
        if p and p not in _seen:
            _seen.add(p)
            platforms.append(p)
    unknown = [p for p in platforms if p not in PLATFORMS]
    if unknown:
        raise HTTPException(
            422, f"unknown platforms: {unknown}")

    # Resolve action row + content payload.
    action: Optional[Dict[str, Any]] = None
    if body.action_id:
        action = await db.ai_employee_actions.find_one(
            {"id": body.action_id, "tenant_id": tenant_id},
            {"_id": 0})
        if not action:
            raise HTTPException(404, "action not found")
        if action.get("status") not in ("approved", "pending"):
            raise HTTPException(
                400, f"action status is '{action.get('status')}' "
                       f"— must be approved or pending")

    text = body.text or (action and (action.get("payload") or {})
                                 .get("draft") or "")
    # Feb-2026 · Phase S1 — for Soshie's publish_blog wiring, the
    # draft body lives under ``draft.text`` (set by the drafter),
    # not ``payload.draft``.  Fall through so both shapes work.
    if not text and action:
        text = ((action.get("draft") or {}).get("text") or "")
    if not text:
        raise HTTPException(
            422,
            "no content — provide `text` OR pass an action_id "
            "whose payload.draft is populated",
        )
    title = body.title or (
        (action and (action.get("payload") or {}).get("title"))
        or (action and (action.get("draft") or {}).get("title"))
        or ""
    )

    # Moderation — regex-only for P1. Non-empty flags do NOT block
    # here (the block happens at approve-time); we surface the
    # flags on the response so the admin dashboard can badge them.
    brand_brain = await db.brand_brain.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "dont_say": 1}) or {}
    mod = moderate(text, dont_say=brand_brain.get("dont_say") or [])

    # Fan out.
    results: List[Dict[str, Any]] = []
    for platform in platforms:
        adapter = get_adapter(platform)
        if adapter is None:
            results.append({"platform": platform,
                              "status": "failed",
                              "error": "adapter module missing"})
            continue
        try:
            res = await adapter.publish_text(
                tenant_id, text,
                link=body.link, title=title, status=body.status,
                article_id=(action and (action.get("payload") or {})
                                          .get("article_id")),
            )
            results.append({"platform": platform,
                              "status": "published", **res})
            await _persist_post(
                tenant_id, user_id, platform, action, res, text,
            )
        except NotImplementedError as e:
            results.append({"platform": platform,
                              "status": "not_configured",
                              "error": str(e)})
            await _persist_post_fail(
                tenant_id, user_id, platform, action, str(e),
            )
        except PublishError as e:
            results.append({"platform": platform,
                              "status": "failed",
                              "error": e.detail,
                              "http_status": e.status})
            await _persist_post_fail(
                tenant_id, user_id, platform, action, e.detail,
            )
        except Exception as e:                                    # noqa: BLE001
            logger.exception("[soshie.publish] %s crash: %s", platform, e)
            results.append({"platform": platform,
                              "status": "failed",
                              "error": f"unexpected: {e}"})
            await _persist_post_fail(
                tenant_id, user_id, platform, action, str(e),
            )

    return {
        "action_id": body.action_id,
        "results": results,
        "moderation": mod,
    }


# ─── Internal executor helper (used by AI Employees approve queue) ──────
async def execute_publish_for_action(
    *,
    action_id: str,
    tenant_id: str,
    user_id: str,
    platforms: List[str],
    text: str,
    title: Optional[str] = None,
    link: Optional[str] = None,
    status: str = "draft",
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """In-process fan-out helper — called from the AI Employees
    ``POST /ai-employees/actions/{aid}/approve`` executor to publish
    an approved ``soshie.publish_blog`` action.  Bypasses HTTP but
    shares the same persistence + idempotency semantics as
    ``POST /soshie/publish``: when ``idempotency_key`` is supplied,
    a prior cached response with a matching body fingerprint is
    replayed instead of re-executing the fan-out.

    Feb-2026 · Phase S1 — the AE approve endpoint calls this with
    ``idempotency_key=f"action-{aid}"`` so a retry mid-publish
    (network glitch to WP + retry) never double-posts.
    """
    endpoint = "POST /soshie/publish"
    body = PublishIn(
        action_id=action_id, platforms=platforms,
        text=text, title=title, link=link, status=status,
    )
    idem_body = body.dict()

    # Idem replay — inline (no ``Request`` object at this seam).
    if idempotency_key:
        row = await db.idempotency_keys.find_one(
            {"tenant_id": tenant_id, "key": idempotency_key,
             "endpoint": endpoint},
            {"_id": 0},
        )
        if row:
            fp = _fingerprint(idem_body)
            if row.get("body_fingerprint") == fp:
                cached_resp = row.get("response")
                if cached_resp:
                    return cached_resp

    resp = await _do_publish_fanout(
        tenant_id=tenant_id, user_id=user_id, body=body,
    )
    if idempotency_key:
        await store_response(
            idempotency_key, endpoint, tenant_id, resp, idem_body,
        )
    return resp


async def _persist_post(tenant_id: str, user_id: str, platform: str,
                              action: Optional[Dict[str, Any]],
                              adapter_result: Dict[str, Any],
                              text: str) -> None:
    """Row in ``social_posts`` (audit) + row in
    ``social_publish_log`` (idempotency dedupe) + row in
    ``audit_logs`` (cross-app audit trail)."""
    action_id = (action or {}).get("id") or ""
    now = now_iso()
    try:
        await db.social_posts.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "platform": platform,
            "action_id": action_id,
            "platform_post_id": str(adapter_result.get("platform_post_id") or ""),
            "permalink": adapter_result.get("url") or "",
            "status": "published",
            "content_text": text[:2000],
            "published_at": now,
            "actor_id": user_id,
        })
    except Exception as e:                                        # noqa: BLE001
        logger.warning("[soshie.publish] social_posts insert failed: %s", e)
    if action_id:
        try:
            await db.social_publish_log.insert_one({
                "tenant_id": tenant_id,
                "action_id": action_id,
                "platform": platform,
                "dispatched_at": now,
                "post_url": adapter_result.get("url") or "",
            })
        except Exception as e:                                    # noqa: BLE001
            # Duplicate-key on the compound-unique index is the
            # idempotency guard doing its job — swallow.
            logger.info(
                "[soshie.publish] social_publish_log dedupe hit: %s", e)
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event": "soshie.publish",
            "at": now,
            "actor_id": user_id,
            "payload": {
                "platform": platform,
                "action_id": action_id,
                "platform_post_id":
                    str(adapter_result.get("platform_post_id") or ""),
                "url": adapter_result.get("url") or "",
            },
        })
    except Exception as e:                                        # noqa: BLE001
        logger.warning("[soshie.publish] audit_logs insert failed: %s", e)


async def _persist_post_fail(tenant_id: str, user_id: str,
                                    platform: str,
                                    action: Optional[Dict[str, Any]],
                                    error: str) -> None:
    action_id = (action or {}).get("id") or ""
    try:
        await db.social_posts.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "platform": platform,
            "action_id": action_id,
            "status": "failed",
            "error": (error or "")[:500],
            "published_at": now_iso(),
            "actor_id": user_id,
        })
    except Exception as e:                                        # noqa: BLE001
        logger.warning("[soshie.publish] failed-row insert failed: %s", e)


# ─── GET /soshie/publish/history ──────────────────────────────────────────
@router.get("/soshie/publish/history")
async def publish_history(
    limit: int = 50,
    platform: Optional[str] = None,
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if platform:
        q["platform"] = platform.strip().lower()
    rows: List[Dict[str, Any]] = []
    async for r in db.social_posts.find(q, {"_id": 0}) \
            .sort("published_at", -1).limit(min(200, max(1, limit))):
        rows.append(r)
    return {"posts": rows, "count": len(rows)}


# ─── POST /soshie/ingest-website ──────────────────────────────────────────
class IngestIn(BaseModel):
    website_url: str


@router.post("/soshie/ingest-website")
async def ingest_website_endpoint(
    body: IngestIn,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Kick off the P1 brand-brain website ingest. Idempotent per
    (tenant, X-Idempotency-Key).  Returns the crawl summary."""
    from services.soshie.brand_ingest import ingest_website
    idem_body = body.dict()
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /soshie/ingest-website", idem_body,
    )
    if cached is not None:
        return cached
    result = await ingest_website(
        tenant["id"], body.website_url, user_id=user["id"])
    if idem_key:
        await store_response(
            idem_key, "POST /soshie/ingest-website",
            tenant["id"], result, idem_body,
        )
    return result
