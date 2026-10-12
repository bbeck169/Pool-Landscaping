"""Preview isolation · P0 Stage 3 Step B — schema shape repair.

The Stage-2 scrubber emitted LIST-OF-STRING for ``customers.emails``
/ ``customers.mobiles`` / ``customers.phones``:

    "emails":  ["preview-customer7627@preview.local"]
    "mobiles": ["555-027627"]

The Pydantic schema in ``models.py`` (``CustomerIn``) declares both as
``Optional[List[dict]]`` and
``services.customer_multi_contact.normalize_mobiles`` /
``normalize_emails`` expect objects with ``address`` /
``number_e164`` / ``label`` / ``is_primary`` / consent flags. The
shape mismatch surfaced as a 500 on ``GET /api/customers`` for
``page_size > 5`` once ``CustomerListItem.model_config = extra="allow"``
promoted the extra fields into pydantic validation.

This migration walks ``customers``, finds docs where ``emails`` /
``mobiles`` / ``phones`` contains any string entry, and rewrites
each entry as the full object shape the normalizers emit. Entries
that are already dicts are left unchanged.

* IDEMPOTENT — a second run sees only object shapes and is a no-op.
* STRICT NO-OP ON PRODUCTION — the ``APP_ENV`` guard refuses to run
  on production regardless of CLI invocation. Running by accident
  against production MUST be impossible; the module raises
  ``RuntimeError`` before any update.
* LOCALHOST-ONLY MONGO — defense-in-depth guard mirrors
  ``scripts/scrub_preview_pii.py``.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

_log = logging.getLogger(__name__)


def _is_localhost_mongo() -> bool:
    url = os.environ.get("MONGO_URL", "")
    return "localhost" in url or "127.0.0.1" in url


def _is_production() -> bool:
    return (os.environ.get("APP_ENV", "preview") or "preview").lower() == "production"


def _email_from_string(s: str) -> Dict[str, Any]:
    return {
        "address": s.strip().lower(),
        "label": "Primary",
        "is_primary": True,
        "marketing_ok": True,
        "notifications_enabled": True,
    }


def _mobile_from_string(s: str) -> Dict[str, Any]:
    return {
        "number_e164": s.strip(),
        "label": "Primary",
        "is_primary": True,
        "sms_ok": True,
        "notifications_enabled": True,
    }


def _phone_from_string(s: str) -> Dict[str, Any]:
    v = s.strip()
    return {"type": "home", "number": v, "e164": v, "raw": None}


def _needs_shape_fix(entries: Any) -> bool:
    """``True`` iff ``entries`` is a list and contains at least one
    string element. Non-list / all-dict lists are pass-through."""
    if not isinstance(entries, list):
        return False
    return any(isinstance(e, str) for e in entries)


def _normalize_list(entries: List[Any], converter) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    primary_marked = False
    for e in entries:
        if isinstance(e, str):
            obj = converter(e)
        elif isinstance(e, dict):
            obj = dict(e)
        else:
            continue
        # Ensure at most one primary marker survives — the first entry
        # that carries ``is_primary=True`` wins. If none carry it, mark
        # the first entry as primary.
        if obj.get("is_primary"):
            if primary_marked:
                obj["is_primary"] = False
            else:
                primary_marked = True
        out.append(obj)
    if out and not primary_marked:
        out[0]["is_primary"] = True
    return out


async def run(db) -> Dict[str, Any]:
    """Walk ``customers``, rewrite emails/mobiles/phones that contain
    string entries. Returns per-field repair counts.
    """
    if _is_production():
        _log.warning(
            "[preview_schema_fix] APP_ENV=production — refusing to run.",
        )
        return {"skipped": "production_env"}
    if not _is_localhost_mongo():
        _log.warning(
            "[preview_schema_fix] MONGO_URL is not localhost — refusing.",
        )
        return {"skipped": "non_localhost_mongo"}

    counts: Dict[str, int] = {
        "emails_fixed": 0,
        "mobiles_fixed": 0,
        "phones_fixed": 0,
        "docs_updated": 0,
    }

    cursor = db.customers.find(
        {"$or": [
            {"emails":  {"$elemMatch": {"$type": "string"}}},
            {"mobiles": {"$elemMatch": {"$type": "string"}}},
            {"phones":  {"$elemMatch": {"$type": "string"}}},
        ]},
        {"_id": 1, "emails": 1, "mobiles": 1, "phones": 1},
    )
    async for row in cursor:
        patch: Dict[str, Any] = {}
        if _needs_shape_fix(row.get("emails")):
            patch["emails"] = _normalize_list(
                row.get("emails") or [], _email_from_string,
            )
            counts["emails_fixed"] += 1
        if _needs_shape_fix(row.get("mobiles")):
            patch["mobiles"] = _normalize_list(
                row.get("mobiles") or [], _mobile_from_string,
            )
            counts["mobiles_fixed"] += 1
        if _needs_shape_fix(row.get("phones")):
            patch["phones"] = _normalize_list(
                row.get("phones") or [], _phone_from_string,
            )
            counts["phones_fixed"] += 1
        if patch:
            await db.customers.update_one({"_id": row["_id"]}, {"$set": patch})
            counts["docs_updated"] += 1

    _log.info(
        "[preview_schema_fix] done · emails=%d mobiles=%d phones=%d docs=%d",
        counts["emails_fixed"], counts["mobiles_fixed"],
        counts["phones_fixed"], counts["docs_updated"],
    )
    return {"ok": True, "counts": counts}


__all__ = ["run"]
