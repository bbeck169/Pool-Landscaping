"""MTH-A · Feb-2026 — Mongo persistence for the AI rule engine.

Two collections:

* ``tenant_ai_rules`` — one doc per tenant.  Unique index on
  ``tenant_id``.
* ``tenant_ai_rules_revisions`` — one immutable doc per historical
  save.  Non-unique index on ``(tenant_id, revision_number desc)``.

Third collection: ``platform_ai_rule_defaults`` — single doc,
super-editable, applied when a tenant has no explicit override.

All mutations go through this module so:
  * revision numbers stay monotonic per tenant,
  * revisions get written every time,
  * the resolver cache is invalidated on save,
  * the 50-KiB doc-size guard is enforced consistently.

Actor snapshot (``last_updated_by`` + ``last_updated_by_name``)
uses whatever the caller passes.  Reason min-length is enforced
here too — the router just forwards the caller's dict.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso

from services.tenant_ai_rules import cache
from services.tenant_ai_rules.schema import (
    MAX_DOC_SIZE_BYTES,
    MIN_REASON_LEN,
    RULE_CATEGORIES,
    default_rules_doc,
    doc_size_bytes,
    validate_category_payload,
)


# ═══════════════════════════════════════════════════════════════════
# Error surface (routers translate → HTTP 400 / 403 / 409)
# ═══════════════════════════════════════════════════════════════════

class RuleStoreError(Exception):
    """Wraps validation / policy failures from the store layer.

    ``error_code`` is stable — used by the router for the 400 body
    and by pytest for assertion strings.
    """

    def __init__(self, error_code: str, message: str,
                  status_code: int = 400,
                  detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}


def _require_reason(reason: Optional[str]) -> str:
    if not isinstance(reason, str):
        raise RuleStoreError(
            "reason_required",
            f"'reason' must be a string of at least "
            f"{MIN_REASON_LEN} characters",
        )
    r = reason.strip()
    if len(r) < MIN_REASON_LEN:
        raise RuleStoreError(
            "reason_too_short",
            f"'reason' must be at least {MIN_REASON_LEN} characters "
            f"(got {len(r)})",
        )
    return r


def _guard_doc_size(doc: Dict[str, Any]) -> None:
    n = doc_size_bytes(doc)
    if n > MAX_DOC_SIZE_BYTES:
        raise RuleStoreError(
            "rule_doc_too_large",
            f"Rules doc {n} bytes > {MAX_DOC_SIZE_BYTES} byte cap",
            status_code=400,
            detail={"size_bytes": n, "limit": MAX_DOC_SIZE_BYTES},
        )


# ═══════════════════════════════════════════════════════════════════
# Platform defaults (single-doc collection)
# ═══════════════════════════════════════════════════════════════════

_PLATFORM_DOC_KEY: str = "singleton"                    # sentinel _id


async def get_platform_defaults() -> Dict[str, Any]:
    """Return the current platform-default rules payload.

    Lazy-inits the singleton row on first read so a fresh cluster
    (or a pytest DB) always has a stable set of defaults to fall
    back to.
    """
    row = await db.platform_ai_rule_defaults.find_one(
        {"key": _PLATFORM_DOC_KEY}, {"_id": 0},
    )
    if row:
        return row
    now = _iso_utcnow()
    seed = {
        "key": _PLATFORM_DOC_KEY,
        "rules": default_rules_doc(),
        "revision_number": 1,
        "last_updated_by": None,
        "last_updated_by_name": "system.bootstrap",
        "last_updated_at": now,
        "last_update_reason": "platform defaults bootstrap",
        "created_at": now,
    }
    try:
        await db.platform_ai_rule_defaults.insert_one(dict(seed))
    except Exception as exc:                                     # noqa: BLE001
        # Two concurrent readers can race for the seed — the loser
        # falls through to a fresh read.  Any other error surfaces.
        logger.warning(
            "[mth-a] platform defaults bootstrap insert failed "
            "(likely dupe): %s", exc,
        )
        row = await db.platform_ai_rule_defaults.find_one(
            {"key": _PLATFORM_DOC_KEY}, {"_id": 0},
        )
        if row:
            return row
        raise
    return dict(seed)


async def save_platform_category(
    *, category: str, value: Any,
    actor: Optional[Dict[str, Any]], reason: str,
) -> Dict[str, Any]:
    """Patch a single category on the platform defaults doc.

    Increments the platform revision counter and invalidates the
    ENTIRE per-tenant cache (platform changes affect every tenant's
    resolved view).
    """
    reason_clean = _require_reason(reason)
    if category not in RULE_CATEGORIES:
        raise RuleStoreError(
            "unknown_category",
            f"unknown rule category {category!r}",
        )
    try:
        normalised = validate_category_payload(category, value)
    except ValueError as exc:
        raise RuleStoreError(
            "validation_failed", str(exc),
            detail={"category": category},
        )
    current = await get_platform_defaults()
    rules = dict(current.get("rules") or default_rules_doc())
    rules[category] = normalised
    new_doc = dict(current)
    new_doc["rules"] = rules
    new_doc["revision_number"] = int(
        current.get("revision_number") or 0
    ) + 1
    new_doc["last_updated_by"] = (actor or {}).get("id")
    new_doc["last_updated_by_name"] = (
        (actor or {}).get("name")
        or (actor or {}).get("email")
        or "unknown"
    )
    new_doc["last_updated_at"] = _iso_utcnow()
    new_doc["last_update_reason"] = reason_clean
    _guard_doc_size(new_doc)
    await db.platform_ai_rule_defaults.update_one(
        {"key": _PLATFORM_DOC_KEY},
        {"$set": {k: v for k, v in new_doc.items() if k != "key"}},
        upsert=True,
    )
    # Platform-level change → invalidate EVERY cached tenant.
    cache.invalidate_all()
    logger.info(
        "[mth-a] platform_ai_rule_defaults saved category=%s "
        "revision=%s actor=%s",
        category, new_doc["revision_number"],
        (actor or {}).get("email"),
    )
    return new_doc


# ═══════════════════════════════════════════════════════════════════
# Tenant rules
# ═══════════════════════════════════════════════════════════════════

def _iso_utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fresh_tenant_doc(tenant_id: str) -> Dict[str, Any]:
    """Build a fresh tenant doc — used by the lazy-init path.

    Platform defaults are inlined into ``rules`` at creation time so
    a tenant that never edits anything still has a coherent
    payload; the resolver still layers current platform defaults
    over top for fields that the tenant hasn't explicitly set.
    """
    platform = await get_platform_defaults()
    now = _iso_utcnow()
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "master_ai_send_live_comms": False,           # safety-first
        "rules": {},                                   # empty overrides
        "revision_number": 0,
        "last_updated_by": None,
        "last_updated_by_name": "system.lazy_init",
        "last_updated_at": now,
        "last_update_reason": "lazy_init_from_platform_defaults",
        "created_at": now,
        "lazy_initialized_from_platform_defaults": True,
        # Snapshot the platform revision at init time so we can
        # detect a stale tenant later on if we ever add drift audits.
        "platform_revision_at_init": platform.get(
            "revision_number",
        ),
    }


async def get_tenant_rules(
    tenant_id: str, *, lazy_init: bool = True,
) -> Optional[Dict[str, Any]]:
    """Return the raw tenant rules doc (with explicit overrides only).

    Does NOT merge platform defaults — see
    :func:`services.tenant_ai_rules.resolver.resolve_rules_for_tenant`
    for the merged view.

    Lazy-inits a doc when the tenant has none and ``lazy_init=True``.
    """
    row = await db.tenant_ai_rules.find_one(
        {"tenant_id": tenant_id}, {"_id": 0},
    )
    if row:
        return row
    if not lazy_init:
        return None
    seed = await _fresh_tenant_doc(tenant_id)
    try:
        await db.tenant_ai_rules.insert_one(dict(seed))
        logger.info(
            "tenant_ai_rules.lazy_init: tenant_id=%s", tenant_id,
        )
    except Exception as exc:                                     # noqa: BLE001
        # Concurrent lazy-init race — the loser reads the winner's
        # row and returns it.
        logger.warning(
            "[mth-a] tenant_ai_rules lazy_init insert race for "
            "tenant=%s (%s) — reading existing row",
            tenant_id, exc,
        )
        row = await db.tenant_ai_rules.find_one(
            {"tenant_id": tenant_id}, {"_id": 0},
        )
        if row:
            return row
        raise
    return seed


async def _bump_and_persist(
    *, tenant_id: str, current: Dict[str, Any],
    updates: Dict[str, Any], actor: Optional[Dict[str, Any]],
    reason_clean: str,
) -> Dict[str, Any]:
    """Apply ``updates`` on top of ``current``, increment the tenant's
    revision counter, persist the new doc, write the immutable
    revision snapshot to ``tenant_ai_rules_revisions``, invalidate
    cache."""
    new_doc = dict(current)
    new_doc.update(updates)
    new_doc["revision_number"] = int(
        current.get("revision_number") or 0
    ) + 1
    new_doc["last_updated_by"] = (actor or {}).get("id")
    new_doc["last_updated_by_name"] = (
        (actor or {}).get("name")
        or (actor or {}).get("email")
        or "unknown"
    )
    new_doc["last_updated_at"] = _iso_utcnow()
    new_doc["last_update_reason"] = reason_clean
    _guard_doc_size(new_doc)

    # Persist the head doc.
    await db.tenant_ai_rules.update_one(
        {"tenant_id": tenant_id},
        {"$set": {k: v for k, v in new_doc.items()
                  if k not in ("tenant_id",)}},
        upsert=True,
    )
    # Immutable revision snapshot.
    revision_row = dict(new_doc)
    revision_row["id"] = new_id()
    revision_row["parent_revision_id"] = current.get("id")
    revision_row["revision_id"] = revision_row["id"]
    await db.tenant_ai_rules_revisions.insert_one(revision_row)
    # Cache invalidation.
    cache.invalidate(tenant_id)
    return new_doc


async def save_category(
    tenant_id: str, category: str, value: Any,
    *, actor: Optional[Dict[str, Any]], reason: str,
) -> Dict[str, Any]:
    """Patch one rule category for the tenant.  Validates + bumps
    revision + writes revision snapshot + invalidates cache."""
    reason_clean = _require_reason(reason)
    if category not in RULE_CATEGORIES:
        raise RuleStoreError(
            "unknown_category",
            f"unknown rule category {category!r}",
        )
    try:
        normalised = validate_category_payload(category, value)
    except ValueError as exc:
        raise RuleStoreError(
            "validation_failed", str(exc),
            detail={"category": category},
        )
    current = await get_tenant_rules(tenant_id)                # lazy-init OK
    rules = dict(current.get("rules") or {})
    rules[category] = normalised
    return await _bump_and_persist(
        tenant_id=tenant_id, current=current,
        updates={"rules": rules,
                 "lazy_initialized_from_platform_defaults": False},
        actor=actor, reason_clean=reason_clean,
    )


async def reset_category(
    tenant_id: str, category: str,
    *, actor: Optional[Dict[str, Any]], reason: str,
) -> Dict[str, Any]:
    """Delete the tenant's override for one category.  Subsequent
    reads see the platform default for that category."""
    reason_clean = _require_reason(reason)
    if category not in RULE_CATEGORIES:
        raise RuleStoreError(
            "unknown_category",
            f"unknown rule category {category!r}",
        )
    current = await get_tenant_rules(tenant_id)
    rules = dict(current.get("rules") or {})
    rules.pop(category, None)
    return await _bump_and_persist(
        tenant_id=tenant_id, current=current,
        updates={"rules": rules,
                 "lazy_initialized_from_platform_defaults": False},
        actor=actor, reason_clean=reason_clean,
    )


async def save_master_switch(
    tenant_id: str, enabled: bool,
    *, actor: Optional[Dict[str, Any]], reason: str,
) -> Dict[str, Any]:
    """Flip the tenant's ``master_ai_send_live_comms`` flag.  Super-
    only (enforced by the router)."""
    reason_clean = _require_reason(reason)
    if not isinstance(enabled, bool):
        raise RuleStoreError(
            "invalid_master_switch_value",
            "'enabled' must be a boolean",
        )
    current = await get_tenant_rules(tenant_id)
    return await _bump_and_persist(
        tenant_id=tenant_id, current=current,
        updates={"master_ai_send_live_comms": enabled,
                 "lazy_initialized_from_platform_defaults": False},
        actor=actor, reason_clean=reason_clean,
    )


async def revert_to_revision(
    tenant_id: str, revision_number: int,
    *, actor: Optional[Dict[str, Any]], reason: str,
) -> Dict[str, Any]:
    """Restore the tenant's rules to a prior revision snapshot.

    Creates a NEW revision (the revert itself) whose ``rules`` +
    ``master_ai_send_live_comms`` match the target revision.  The
    revert row's ``last_update_reason`` records the target so a
    future audit can spot revert chains.
    """
    reason_clean = _require_reason(reason)
    if not isinstance(revision_number, int) or revision_number < 1:
        raise RuleStoreError(
            "invalid_revision_number",
            "'revision_number' must be a positive int",
        )
    target = await db.tenant_ai_rules_revisions.find_one(
        {"tenant_id": tenant_id, "revision_number": revision_number},
        {"_id": 0},
    )
    if not target:
        raise RuleStoreError(
            "revision_not_found",
            f"revision {revision_number} not found for tenant",
            status_code=404,
        )
    current = await get_tenant_rules(tenant_id)
    return await _bump_and_persist(
        tenant_id=tenant_id, current=current,
        updates={
            "rules": dict(target.get("rules") or {}),
            "master_ai_send_live_comms":
                bool(target.get("master_ai_send_live_comms", False)),
            "lazy_initialized_from_platform_defaults": False,
        },
        actor=actor,
        reason_clean=(f"revert_to_revision={revision_number}; "
                        f"{reason_clean}"),
    )


async def list_revisions(
    tenant_id: str, *, limit: int = 100,
) -> List[Dict[str, Any]]:
    """List revisions newest-first, capped at ``limit`` (max 500)."""
    lim = max(1, min(int(limit or 100), 500))
    cursor = db.tenant_ai_rules_revisions.find(
        {"tenant_id": tenant_id},
        {"_id": 0},
    ).sort("revision_number", -1).limit(lim)
    return await cursor.to_list(lim)
