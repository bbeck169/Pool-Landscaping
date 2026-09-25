#!/usr/bin/env python3
# ============================================================
# NO-STRIPE BANNER · Task Q · Feb-2026 · Preview ops only.
# ============================================================
#   This script performs a DIRECT-DB manual-override unlock for
#   a target tenant. It intentionally NEVER touches Stripe:
#     * No imports from ``routers.feature_marketplace`` /
#       ``routers.marketplace*`` / ``services.payments.*`` /
#       ``services.stripe*`` / the ``stripe`` PyPI SDK.
#     * No Stripe fields written on the ``feature_entitlements``
#       rows — only the ``manual_override`` shape recognised by
#       ``services.entitlements.check.is_entitlement_active``.
#     * No writes to ``stripe_subscriptions`` /
#       ``stripe_customers`` / any Stripe-adjacent collection.
#
#   PRODUCTION tenants MUST use the marketplace HTTP flow
#   (POST /api/tenants/mine/feature-marketplace/{key}/enable)
#   which handles Stripe billing. This script is preview-only.
# ============================================================
"""Task Q · Feb-2026 — CLI ops override for tenant feature
entitlements (preview boxes / comped accounts).

Idempotent. Safe to re-run. Never exposed via HTTP.

Usage::

    python backend/scripts/ops_unlock_tenant_features.py
    python backend/scripts/ops_unlock_tenant_features.py \\
        --tenant-id affdfbfa-88b9-4baa-ae45-2ef78531b6e4 \\
        --user-email brian@plofv.com
    python backend/scripts/ops_unlock_tenant_features.py \\
        --reason "Preview unlock — no Stripe · Task Q"

For each of the 4 preview features (``zillow_data``,
``seo_heatmap``, ``ai_analytics``, ``ai_copilot``):

  1. Upsert a ``feature_entitlements`` row with
     ``enabled=True`` + ``billing_status="manual_override"``.
     Idempotent — pre-existing manual-override rows are
     detected and reported as ``already-enabled · no-op``
     (matches the ``seed_seo_heatmap_entitlement.py`` shape;
     ``enabled_at`` is preserved on no-op runs).
  2. If the feature is ``ai_analytics``, also ``$set`` the
     dotted path ``settings.ai.analytics_enabled = True`` on
     the tenant doc so the layered
     ``ai_analytics_effective_gate`` returns allowed. Sibling
     keys under ``settings.ai`` (``kb_uploads_enabled``,
     ``persona_name``, …) are preserved.

For the target user (``--user-email``):

  * Missing → HALT (do NOT create).
  * On a different ``tenant_id`` → HALT (do NOT reassign).
  * On the target tenant, role != ``super_admin`` → ``$set``
    role to ``super_admin`` + log the pre-image role.
  * Already ``super_admin`` on the target tenant → no write
    issued; log ``already-super_admin · no-op``.

Exit codes:
    * 0 — success (all writes idempotent + user check passed).
    * 1 — env / connection / write failure OR halt condition
          (missing user, cross-tenant collision, phantom key).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── Path bootstrap so ``services.entitlements.*`` imports work
# regardless of the CWD the operator runs the script from. ──────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


try:
    from dotenv import dotenv_values                                  # noqa: E402
    from pymongo import MongoClient                                   # noqa: E402
    from services.entitlements.check import (                         # noqa: E402
        BILLING_STATUS_MANUAL_OVERRIDE,
    )
    from services.entitlements.registry import FEATURE_KEYS           # noqa: E402
except ImportError as exc:                                            # pragma: no cover
    print(f"[ops-unlock] import failed: {exc}", file=sys.stderr)
    sys.exit(1)


# ── Hard NO-STRIPE guard ────────────────────────────────────────
# Belt-and-suspenders assertion: fail immediately if a future
# refactor accidentally lands a Stripe / marketplace import
# above.  Cheap runtime check that costs ~0 and blocks the
# script from executing under a poisoned import graph.
_FORBIDDEN_MODULES = (
    "stripe",
    "routers.feature_marketplace",
    "routers.marketplace",
    "services.payments.stripe_charge",
    "services.payments.tenant_stripe",
)
for _mod in _FORBIDDEN_MODULES:
    assert _mod not in sys.modules, (
        f"[ops-unlock] NO-STRIPE guard tripped: "
        f"forbidden module '{_mod}' is loaded before script runs. "
        f"Refusing to continue."
    )


# ── Defaults (all overridable via argparse) ─────────────────────
_PREVIEW_TENANT_ID = "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"
_PREVIEW_USER_EMAIL = "brian@plofv.com"
_DEFAULT_REASON = "Preview unlock — no Stripe · Task Q"
_SEED_SENTINEL = "__seed_script__"

# The 4 features Task Q unlocks. Every key MUST be a member of
# the registry (see registry-guard below) — a phantom key would
# create a row no ``has_feature()`` call ever consumes.
_TARGET_FEATURES = ("zillow_data", "seo_heatmap", "ai_analytics", "ai_copilot")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env() -> tuple[str, str]:
    """Read MONGO_URL + DB_NAME from ``backend/.env`` or the
    process environment. Never hardcoded."""
    dotenv = dotenv_values(_BACKEND_DIR / ".env")
    mongo = dotenv.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = dotenv.get("DB_NAME") or os.environ.get("DB_NAME")
    if not mongo or not db_name:
        raise RuntimeError(
            "MONGO_URL / DB_NAME missing from backend/.env and environment"
        )
    return mongo, db_name


def _project_entitlement(doc: dict | None) -> dict:
    """Return only the audit-relevant fields — never leak Stripe
    identifiers or Mongo ``_id`` from console output. Same
    projection surface as ``seed_seo_heatmap_entitlement.py``
    with ``feature_key`` added so the multi-key log is readable."""
    if not doc:
        return {}
    return {
        k: doc.get(k) for k in (
            "feature_key", "enabled", "billing_status", "enabled_at",
            "enabled_by", "enabled_reason", "cancels_at", "updated_at",
        )
    }


def _project_ai_settings(tenant_doc: dict | None) -> dict:
    """Return every key under ``settings.ai`` so the operator can
    verify siblings (``kb_uploads_enabled``, ``persona_name``,
    …) survived the dotted ``$set``."""
    if not tenant_doc:
        return {}
    return dict(((tenant_doc.get("settings") or {}).get("ai") or {}))


def _upsert_entitlement(
    db, *, tenant_id: str, feature_key: str, reason: str,
) -> str:
    """Perform the idempotent entitlement upsert. Returns a
    single-word action tag: ``"already-enabled"`` |
    ``"inserted"`` | ``"updated"`` | ``"no-op"``.

    Idempotency contract matches ``seed_seo_heatmap_entitlement``:
    if ``enabled=True`` + ``billing_status="manual_override"``
    already, we short-circuit BEFORE any $set so ``enabled_at``
    + ``updated_at`` remain frozen at the original values.
    """
    pre = db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    print(f"[ops-unlock][{feature_key}] pre  = "
          f"{json.dumps(_project_entitlement(pre)) if pre else '(no row)'}")

    if (
        pre
        and bool(pre.get("enabled")) is True
        and str(pre.get("billing_status") or "").lower()
            == BILLING_STATUS_MANUAL_OVERRIDE
    ):
        print(f"[ops-unlock][{feature_key}] action = already-enabled (no-op)")
        return "already-enabled"

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

    action = (
        "inserted"    if res.upserted_id is not None
        else "updated" if res.modified_count > 0
        else "no-op"
    )
    print(f"[ops-unlock][{feature_key}] action = {action}")

    post = db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    print(f"[ops-unlock][{feature_key}] post = "
          f"{json.dumps(_project_entitlement(post))}")
    return action


def _set_analytics_enabled(db, *, tenant_id: str) -> str:
    """Dotted-path ``$set`` so siblings under ``settings.ai``
    are preserved. Returns an action tag: ``"unchanged"`` |
    ``"set"``. Logs pre + post images of the ``settings.ai``
    sub-doc so the operator can eyeball sibling preservation."""
    pre_tenant = db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "settings.ai": 1},
    )
    pre_ai = _project_ai_settings(pre_tenant)
    print(f"[ops-unlock][settings.ai] pre  = {json.dumps(pre_ai)}")

    if pre_ai.get("analytics_enabled") is True:
        print("[ops-unlock][settings.ai] action = unchanged "
              "(analytics_enabled already True)")
        return "unchanged"

    db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"settings.ai.analytics_enabled": True}},
    )

    post_tenant = db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "settings.ai": 1},
    )
    post_ai = _project_ai_settings(post_tenant)
    print(f"[ops-unlock][settings.ai] post = {json.dumps(post_ai)}")

    # Belt-and-suspenders: siblings must survive the dotted $set.
    for sibling in pre_ai:
        assert sibling in post_ai, (
            f"[ops-unlock] sibling '{sibling}' under settings.ai "
            f"lost during $set — refusing to continue"
        )
    print("[ops-unlock][settings.ai] action = set (siblings preserved)")
    return "set"


def _ensure_super_admin(db, *, tenant_id: str, user_email: str) -> str:
    """Verify the target user is a ``super_admin`` on the target
    tenant. Halt on missing / cross-tenant / phantom cases.
    Returns action tag: ``"already-super_admin"`` |
    ``"promoted"``."""
    rows = list(db.users.find(
        {"email": user_email},
        {"_id": 0, "id": 1, "email": 1, "tenant_id": 1, "role": 1},
    ))
    if not rows:
        raise RuntimeError(
            f"[ops-unlock][user] HALT — user '{user_email}' does not "
            f"exist. Out of scope: this script does NOT create users. "
            f"Re-run after seeding the user manually."
        )
    on_target = [r for r in rows if r.get("tenant_id") == tenant_id]
    if not on_target:
        raise RuntimeError(
            f"[ops-unlock][user] HALT — user '{user_email}' exists "
            f"but on a DIFFERENT tenant "
            f"(found tenants: {[r.get('tenant_id') for r in rows]}). "
            f"Refusing to silently reassign."
        )
    user = on_target[0]
    print(f"[ops-unlock][user] pre  = {json.dumps(user)}")
    if (user.get("role") or "").lower() == "super_admin":
        print("[ops-unlock][user] action = already-super_admin (no-op)")
        return "already-super_admin"

    old_role = user.get("role")
    db.users.update_one(
        {"id": user["id"]},
        {"$set": {"role": "super_admin"}},
    )
    print(f"[ops-unlock][user] action = promoted (old_role={old_role!r})")
    return "promoted"


def _append_ops_log(*, tenant_id: str, user_email: str, actions: dict) -> None:
    """Append the run to ``memory/ops_log.md`` (create if
    missing). Ops-only — never referenced by application code."""
    log_path = _BACKEND_DIR.parent / "memory" / "ops_log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not log_path.exists()
    with log_path.open("a", encoding="utf-8") as fh:
        if header_needed:
            fh.write("# Ops log · Preview environment\n\n")
            fh.write(
                "One-line-per-run audit trail for direct-DB ops "
                "overrides performed on the preview environment. "
                "Never touch production.\n\n"
            )
        fh.write(f"## {_now_iso()} · Task Q · Preview unlock — no Stripe\n\n")
        fh.write(f"- tenant_id: `{tenant_id}`\n")
        fh.write(f"- user_email: `{user_email}`\n")
        fh.write(f"- features: {', '.join(_TARGET_FEATURES)}\n")
        fh.write(f"- actions: {json.dumps(actions)}\n")
        fh.write("- operator note: Preview unlock — no Stripe.\n\n")


def run(*, tenant_id: str, user_email: str, reason: str) -> int:
    """Top-level orchestrator. Returns the process exit code."""
    print(f"[ops-unlock] target tenant_id = {tenant_id}")
    print(f"[ops-unlock] target user      = {user_email}")
    print(f"[ops-unlock] features         = {list(_TARGET_FEATURES)}")
    print(f"[ops-unlock] reason           = {reason!r}")

    # ── Registry guard — every requested key must be a real,
    # registered feature. A phantom key would produce a row no
    # ``has_feature()`` check ever consumes. ────────────────────
    for key in _TARGET_FEATURES:
        assert key in FEATURE_KEYS, (
            f"[ops-unlock] HALT — feature key '{key}' is not in "
            f"the registry (FEATURE_KEYS={list(FEATURE_KEYS)}). "
            f"Refusing to write a phantom entitlement row."
        )
    print(f"[ops-unlock] registry guard   = ok "
          f"(all {len(_TARGET_FEATURES)} keys registered)")

    try:
        mongo_url, db_name = _load_env()
    except RuntimeError as exc:
        print(f"[ops-unlock] {exc}", file=sys.stderr)
        return 1

    try:
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[db_name]
    except Exception as exc:                                          # noqa: BLE001
        print(f"[ops-unlock] mongo connect failed: {exc}", file=sys.stderr)
        return 1

    # ── Freeze the untouchable Stripe counts so the operator
    # can eyeball the invariant. We NEVER write to these — the
    # snapshot is diagnostic only. ────────────────────────────
    stripe_subs = db.stripe_subscriptions.count_documents({"tenant_id": tenant_id})
    stripe_charges_cnt = db.stripe_charges.count_documents({"tenant_id": tenant_id})
    print(f"[ops-unlock][invariant] stripe_subscriptions.count "
          f"(tenant scoped) = {stripe_subs} · MUST NOT CHANGE")
    print(f"[ops-unlock][invariant] stripe_charges.count "
          f"(tenant scoped) = {stripe_charges_cnt} · MUST NOT CHANGE")

    actions: dict = {}
    try:
        for key in _TARGET_FEATURES:
            actions[key] = _upsert_entitlement(
                db, tenant_id=tenant_id, feature_key=key, reason=reason,
            )
        actions["settings.ai.analytics_enabled"] = _set_analytics_enabled(
            db, tenant_id=tenant_id,
        )
        actions["user_role"] = _ensure_super_admin(
            db, tenant_id=tenant_id, user_email=user_email,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        client.close()
        return 1

    # ── Re-check invariants ────────────────────────────────────
    stripe_subs_post = db.stripe_subscriptions.count_documents({"tenant_id": tenant_id})
    stripe_charges_post = db.stripe_charges.count_documents({"tenant_id": tenant_id})
    print(f"[ops-unlock][invariant] stripe_subscriptions.count "
          f"post = {stripe_subs_post} "
          f"(expected {stripe_subs} → "
          f"{'OK' if stripe_subs_post == stripe_subs else 'DRIFTED'})")
    print(f"[ops-unlock][invariant] stripe_charges.count "
          f"post = {stripe_charges_post} "
          f"(expected {stripe_charges_cnt} → "
          f"{'OK' if stripe_charges_post == stripe_charges_cnt else 'DRIFTED'})")
    assert stripe_subs_post == stripe_subs, (
        "[ops-unlock] stripe_subscriptions count drifted — refusing to log"
    )
    assert stripe_charges_post == stripe_charges_cnt, (
        "[ops-unlock] stripe_charges count drifted — refusing to log"
    )

    _append_ops_log(
        tenant_id=tenant_id, user_email=user_email, actions=actions,
    )
    print(f"[ops-unlock] actions summary  = {json.dumps(actions)}")
    print("[ops-unlock] ✔ done")
    client.close()
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Task Q · Feb-2026 · PREVIEW-ONLY manual_override unlock "
            "for tenant feature entitlements. NEVER for production. "
            "NEVER touches Stripe."
        ),
    )
    parser.add_argument(
        "--tenant-id", default=_PREVIEW_TENANT_ID,
        help=f"Target tenant id (default: {_PREVIEW_TENANT_ID})",
    )
    parser.add_argument(
        "--user-email", default=_PREVIEW_USER_EMAIL,
        help=f"Target user email (default: {_PREVIEW_USER_EMAIL})",
    )
    parser.add_argument(
        "--reason", default=_DEFAULT_REASON,
        help=f"Free-form audit note (default: {_DEFAULT_REASON!r})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    return run(
        tenant_id=args.tenant_id,
        user_email=args.user_email,
        reason=args.reason,
    )


if __name__ == "__main__":                                            # pragma: no cover
    sys.exit(main())
