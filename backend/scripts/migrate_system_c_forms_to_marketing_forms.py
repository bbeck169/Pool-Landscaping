"""One-shot migration · System C ``db.forms`` → System A ``db.marketing_forms``.

TD-50 · Feb-2026 — Marketing Forms Builder deprecation of System C
public forms (``routers/marketing.py:/forms*`` + ``db.forms`` +
``Phase14Pages.jsx::FormsList``).

This script is **idempotent** — safe to re-run any number of times.
It makes exactly ZERO destructive writes.  System C stays functional
after a run; the goal is to copy each legacy row into
``db.marketing_forms`` with a matching slug so the public widget
path (``routers/marketing_forms.py``) + the admin Marketing Forms
Builder surface can take over at the operator's convenience.

Key invariants preserved:

  * ``db.form_submissions.form_id`` is BYTE-identical pre- and
    post-migration — the two systems have always shared this
    collection, so no submission relinking is required.
  * ``db.forms`` rows are LEFT IN PLACE until the operator issues
    a separate hard-delete pass (follow-up atomic). System C
    endpoints keep working off the untouched rows.
  * Legacy field shape ``{key, label, type, required}`` is
    translated to the modern shape ``{name, label, type, required,
    id}`` — ``key`` becomes ``name``; ``id`` is auto-derived by
    the Marketing Forms admin PATCH on first edit (we leave it
    unset here so the normal normaliser owns id-stability).

Usage::

    # Audit only — no writes.
    python backend/scripts/migrate_system_c_forms_to_marketing_forms.py --audit

    # Dry-run — show what WOULD happen.
    python backend/scripts/migrate_system_c_forms_to_marketing_forms.py --dry-run

    # Migrate for real.
    python backend/scripts/migrate_system_c_forms_to_marketing_forms.py

Exits with status 0 on success, 1 on a hard DB error.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Resolve the backend package root so this module can be invoked
# as either ``python backend/scripts/migrate…`` or
# ``python -m backend.scripts.migrate…``.
_BACKEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir),
)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import db  # noqa: E402

logger = logging.getLogger("td50-migrate")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
    ))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ──────────────────────────────────────────────────────────────────
# Field-shape translator
# ──────────────────────────────────────────────────────────────────
def translate_legacy_field(f: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a System C field (``{key, label, type, required}``)
    to the modern Marketing Forms shape (``{name, label, type,
    required, options?}``).  ``id`` is intentionally omitted so the
    Marketing Forms admin normaliser can derive it on first PATCH.

    Legacy types that have no modern equivalent are passed through
    verbatim — the Marketing Forms _FIELD_TYPES check will 422 on
    save, which surfaces the issue to the operator before any data
    corruption.
    """
    out: Dict[str, Any] = {
        "name": f.get("key") or f.get("name") or "",
        "label": f.get("label") or f.get("key") or "",
        "type": f.get("type") or "text",
        "required": bool(f.get("required", False)),
    }
    if f.get("options"):
        out["options"] = list(f["options"])
    if f.get("placeholder"):
        out["placeholder"] = f["placeholder"]
    return out


def translate_legacy_form(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Build the ``db.marketing_forms`` doc shape from a legacy
    ``db.forms`` row.  Preserves ``id`` (so the shared
    ``form_submissions.form_id`` FK stays stable) + ``slug`` +
    ``tenant_id``.
    """
    now = doc.get("updated_at") or doc.get("created_at") or ""
    return {
        "id": doc["id"],
        "tenant_id": doc["tenant_id"],
        "slug": doc.get("slug") or doc.get("id"),
        "name": doc.get("name") or "Untitled form",
        "fields": [
            translate_legacy_field(f) for f in (doc.get("fields") or [])
        ],
        "submit_button_label": doc.get("submit_button_label") or "Send",
        "success_message": (
            doc.get("success_message") or "Thanks! We'll be in touch."
        ),
        "submit_config": {
            "creates": _map_destination(doc.get("destination")),
            "admin_bell": True,
            "confirmation_email_template_id": None,
            "drip_sequence_id": None,
        },
        "theme": {},
        "hero": None,
        "active": doc.get("status") == "published",
        "submission_count": 0,
        "version": 1,
        "created_at": doc.get("created_at") or now,
        "updated_at": now,
        # TD-50 migration marker so the admin UI can distinguish
        # migrated-from-legacy rows if the operator wants a filter.
        "migrated_from_system_c": True,
    }


def _map_destination(d: Optional[str]) -> str:
    """System C ``destination`` → Marketing Forms ``submit_config.creates``.

    System C used free-form strings; the modern enum is tight.
    Unknown values fall back to ``"lead"`` (the Marketing Forms
    default) so the migration can never 422 at save time.
    """
    if not d:
        return "lead"
    s = str(d).lower().strip()
    if s in ("lead", "customer", "both"):
        return s
    if s in ("booking", "booking_request"):
        return "booking"
    if s in ("service_log", "service"):
        return "service_log"
    if s in ("quote", "quote_request", "estimate"):
        return "quote_request"
    return "lead"


# ──────────────────────────────────────────────────────────────────
# Audit
# ──────────────────────────────────────────────────────────────────
async def audit() -> Dict[str, Any]:
    """Count live ``db.forms`` rows + submissions grouped by tenant.
    Returns a serialisable summary dict that the caller can log /
    exit with.
    """
    legacy_forms = await db.forms.find(
        {}, {"_id": 0, "id": 1, "tenant_id": 1, "slug": 1, "name": 1}
    ).to_list(10_000)
    per_tenant: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"forms": 0, "submissions": 0, "slugs": []},
    )
    for f in legacy_forms:
        t = per_tenant[f["tenant_id"]]
        t["forms"] += 1
        t["slugs"].append(f.get("slug") or f["id"])
    # Count submissions whose form_id references a legacy form.
    legacy_ids = {f["id"] for f in legacy_forms}
    if legacy_ids:
        subs = await db.form_submissions.find(
            {"form_id": {"$in": list(legacy_ids)}},
            {"_id": 0, "tenant_id": 1},
        ).to_list(100_000)
        for s in subs:
            per_tenant[s["tenant_id"]]["submissions"] += 1
    summary = {
        "total_legacy_forms": len(legacy_forms),
        "total_legacy_submissions": sum(
            v["submissions"] for v in per_tenant.values()
        ),
        "per_tenant": dict(per_tenant),
    }
    return summary


# ──────────────────────────────────────────────────────────────────
# Migrate
# ──────────────────────────────────────────────────────────────────
async def migrate(dry_run: bool = False) -> Dict[str, Any]:
    """Idempotent migration.  Returns a report with keys:
    - migrated: list of {id, slug, tenant_id, action}
      where action ∈ ``inserted`` | ``skipped-already-migrated``
    - errors: list of {id, slug, reason}
    """
    legacy_forms = await db.forms.find({}, {"_id": 0}).to_list(10_000)
    report: Dict[str, Any] = {"migrated": [], "errors": [], "dry_run": dry_run}
    for row in legacy_forms:
        try:
            fid = row["id"]
            tenant_id = row["tenant_id"]
            slug = row.get("slug") or fid
            # Idempotency key: a marketing_forms row with the same id
            # (preferred) OR the same (slug, tenant_id).  Either hit
            # means we've migrated this one before.
            existing = await db.marketing_forms.find_one(
                {"$or": [
                    {"id": fid, "tenant_id": tenant_id},
                    {"slug": slug, "tenant_id": tenant_id},
                ]},
                {"_id": 0, "id": 1, "slug": 1},
            )
            if existing:
                report["migrated"].append({
                    "id": fid, "slug": slug, "tenant_id": tenant_id,
                    "action": "skipped-already-migrated",
                    "existing_marketing_form_id": existing["id"],
                })
                continue
            new_doc = translate_legacy_form(row)
            if not dry_run:
                await db.marketing_forms.insert_one(new_doc)
            report["migrated"].append({
                "id": fid, "slug": slug, "tenant_id": tenant_id,
                "action": "inserted" if not dry_run else "would-insert",
            })
        except Exception as exc:  # noqa: BLE001 — report + continue
            report["errors"].append({
                "id": row.get("id"), "slug": row.get("slug"),
                "reason": repr(exc),
            })
    return report


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--audit", action="store_true",
                      help="Audit only — count rows + submissions; no writes.")
    grp.add_argument("--dry-run", action="store_true",
                      help="Show what WOULD be migrated; no writes.")
    return p.parse_args()


async def _main_async() -> int:
    args = _parse_args()
    if args.audit:
        summary = await audit()
        logger.info("[audit] total legacy forms: %d",
                       summary["total_legacy_forms"])
        logger.info("[audit] total legacy submissions: %d",
                       summary["total_legacy_submissions"])
        for tid, info in summary["per_tenant"].items():
            logger.info("[audit]   tenant %s: forms=%d submissions=%d",
                           tid, info["forms"], info["submissions"])
        return 0
    report = await migrate(dry_run=args.dry_run)
    inserted = sum(
        1 for r in report["migrated"] if r["action"] == "inserted"
    )
    skipped = sum(
        1 for r in report["migrated"]
        if r["action"] == "skipped-already-migrated"
    )
    would = sum(
        1 for r in report["migrated"] if r["action"] == "would-insert"
    )
    logger.info("[migrate] dry_run=%s inserted=%d skipped=%d would_insert=%d errors=%d",
                   args.dry_run, inserted, skipped, would,
                   len(report["errors"]))
    if report["errors"]:
        for e in report["errors"]:
            logger.error("[migrate] error on form %s (slug %s): %s",
                           e["id"], e["slug"], e["reason"])
        return 1
    return 0


def main() -> int:  # pragma: no cover — CLI entrypoint
    return asyncio.run(_main_async())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
