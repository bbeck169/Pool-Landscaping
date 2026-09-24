#!/usr/bin/env python3
# PREVIEW-ONLY BYPASS. Production tenants MUST use the marketplace flow
# (POST /api/tenants/mine/feature-marketplace/{key}/enable) which handles
# Stripe billing. This script is for preview/dev bootstrap only.
#
# Direct-DB path chosen over the HTTP force-on endpoint so this script
# works without a running backend + super-admin session token. Same write
# shape (billing_status="manual_override" + BILLING_STATUS_MANUAL_OVERRIDE
# recognition path from Commit 3).
"""Task J · Commit 4 · Feb-2026 — CLI seed for the ``seo_heatmap``
entitlement on a preview / dev tenant.

Idempotent. Safe to re-run. Never exposed via HTTP.

Usage::

    python backend/scripts/seed_seo_heatmap_entitlement.py
    python backend/scripts/seed_seo_heatmap_entitlement.py <tenant_id>
    python backend/scripts/seed_seo_heatmap_entitlement.py --feature-key seo_heatmap --reason "preview bootstrap"

Exit codes:
    * 0 — success (upsert happened OR already-enabled no-op).
    * 1 — env / connection / write failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Path bootstrap so ``services.entitlements.check`` imports ──────
# Script may be invoked from anywhere (CWD unknown); add /app/backend
# to sys.path so the constant import works without pip-installing.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from dotenv import dotenv_values                                  # noqa: E402
    from pymongo import MongoClient                                   # noqa: E402
    from services.entitlements.check import (                         # noqa: E402
        BILLING_STATUS_MANUAL_OVERRIDE,
    )
except ImportError as exc:                                            # pragma: no cover
    print(f"[seed-seo-heatmap] import failed: {exc}", file=sys.stderr)
    sys.exit(1)


# Preview tenant id for Pool & Landscaping of Vistancia. Baked in as
# the CLI default so an ops engineer can run the script bare on the
# preview box. All other tenants MUST be passed explicitly.
_PREVIEW_TENANT_ID = "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"
_DEFAULT_FEATURE_KEY = "seo_heatmap"
_DEFAULT_REASON = "Preview bootstrap for SEO Rank Heatmap"
_SEED_SENTINEL = "__seed_script__"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env() -> tuple[str, str]:
    """Read MONGO_URL + DB_NAME from ``backend/.env`` or the process
    environment. Preserves the ENVIRONMENT SETUP contract that mandates
    ``MONGO_URL`` never be hardcoded."""
    dotenv = dotenv_values(_BACKEND_DIR / ".env")
    mongo = dotenv.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = dotenv.get("DB_NAME") or os.environ.get("DB_NAME")
    if not mongo or not db_name:
        raise RuntimeError(
            "MONGO_URL / DB_NAME missing from backend/.env and environment"
        )
    return mongo, db_name


def _project_display(doc: dict | None) -> dict:
    """Return only the fields the ask asked us to print — never leak
    Stripe identifiers or Mongo _id from console output."""
    if not doc:
        return {}
    return {
        k: doc.get(k) for k in (
            "enabled", "billing_status", "enabled_at",
            "enabled_by", "enabled_reason",
        )
    }


def seed(tenant_id: str, feature_key: str, reason: str) -> int:
    """Perform the idempotent upsert. Returns the process exit code."""
    print(f"[seed-seo-heatmap] target tenant_id  = {tenant_id}")
    print(f"[seed-seo-heatmap] target feature    = {feature_key}")
    try:
        mongo_url, db_name = _load_env()
    except RuntimeError as exc:
        print(f"[seed-seo-heatmap] {exc}", file=sys.stderr)
        return 1
    try:
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[db_name]
    except Exception as exc:                                          # noqa: BLE001
        print(f"[seed-seo-heatmap] mongo connect failed: {exc}",
              file=sys.stderr)
        return 1

    pre = db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    print("[seed-seo-heatmap] pre-state         =",
          json.dumps(_project_display(pre)) if pre else "(no row)")

    # Idempotency short-circuit — already flipped on via manual override.
    if (
        pre
        and bool(pre.get("enabled")) is True
        and str(pre.get("billing_status") or "").lower()
            == BILLING_STATUS_MANUAL_OVERRIDE
    ):
        print("[seed-seo-heatmap] action            = already-enabled")
        print("[seed-seo-heatmap] post-state        =",
              json.dumps(_project_display(pre)))
        client.close()
        return 0

    now = _now_iso()
    set_doc = {
        "tenant_id":       tenant_id,
        "feature_key":     feature_key,
        "enabled":         True,
        "billing_status":  BILLING_STATUS_MANUAL_OVERRIDE,
        "enabled_at":      now,
        "enabled_by":      _SEED_SENTINEL,
        "enabled_reason":  reason,
        "cancels_at":      None,
        "updated_at":      now,
    }
    try:
        res = db.feature_entitlements.update_one(
            {"tenant_id": tenant_id, "feature_key": feature_key},
            {
                "$set":         set_doc,
                "$setOnInsert": {
                    "id":         str(uuid.uuid4()),
                    "created_at": now,
                },
            },
            upsert=True,
        )
    except Exception as exc:                                          # noqa: BLE001
        print(f"[seed-seo-heatmap] upsert failed: {exc}", file=sys.stderr)
        client.close()
        return 1

    action = (
        "inserted"    if res.upserted_id is not None
        else "updated" if res.modified_count > 0
        else "no-op"
    )
    print(f"[seed-seo-heatmap] action            = {action}")

    post = db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    print("[seed-seo-heatmap] post-state        =",
          json.dumps(_project_display(post)))
    client.close()
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "PREVIEW-ONLY: idempotently seed the seo_heatmap entitlement "
            "(manual_override) for a target tenant. Never for production."
        ),
    )
    parser.add_argument(
        "tenant_id", nargs="?", default=_PREVIEW_TENANT_ID,
        help=(
            f"Target tenant id (default: preview tenant "
            f"{_PREVIEW_TENANT_ID})"
        ),
    )
    parser.add_argument(
        "--feature-key", default=_DEFAULT_FEATURE_KEY,
        help=f"Feature key to enable (default: {_DEFAULT_FEATURE_KEY!r})",
    )
    parser.add_argument(
        "--reason", default=_DEFAULT_REASON,
        help="Free-form audit note recorded on the row",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    return seed(args.tenant_id, args.feature_key, args.reason)


if __name__ == "__main__":                                            # pragma: no cover
    sys.exit(main())
