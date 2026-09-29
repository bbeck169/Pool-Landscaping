"""TE-portal-job · Feb-2026 — Per-tenant marketing-template lookup helper.

Shared reader for the transactional templates seeded by
``migrations/te_portal_job_templates_seed.py`` (portal_invite_email +
job_completion_sms). Callers:

* ``routers/portal_admin.py::_try_send_reset_email`` — pulls the
  ``portal_invite_email`` body/subject before the send, falls back
  to the hardcoded module-level constants on miss.
* ``routers/service_reports.py::_bg_send_completion_sms`` — pulls
  the ``job_completion_sms`` body, threads it through
  ``build_completion_sms_body`` as ``body_template=...`` before the
  send. Missing/inactive → the caller keeps the i18n loader + inline
  hardcoded fallback chain.

Design notes
────────────
* No caching in this commit. Both call sites are low-frequency
  (per-invite / per-completion) so a single ``find_one`` per send
  costs nothing measurable.
* ``config.db`` is read at CALL time (not import time) so the module
  is inherently loop-safe under the F7 pytest loop-rebind fixture.
  This avoids adding another entry to ``tests/_f7_loop_fixture.py``'s
  ``_REBOUND_MODULES`` shared list — the module has zero module-level
  ``db`` binding to rebind.
* Tenant scope is enforced in the query — a caller cannot
  accidentally leak another tenant's template.
* The ``marketing_templates`` collection has TWO legacy field-name
  conventions for the active flag:
    - ``add_card_links.py`` writes ``is_active``.
    - ``routers/marketing_templates.py::DEFAULT_SEED`` writes
      ``active``.
  Either being explicitly ``False`` disqualifies the row; a row
  missing both fields defaults to active (matches the router's
  list-endpoint semantics when no ``active`` query param is passed).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import config


async def get_template_by_code(
    code: str, tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the tenant's ``marketing_templates`` row for ``code``,
    or ``None`` when missing / inactive.

    Both callers treat a ``None`` return as "fall through to the
    hardcoded fallback"; a truthy return replaces the hardcoded copy
    with the DB body/subject.
    """
    if not code or not tenant_id:
        return None
    row = await config.db.marketing_templates.find_one(
        {"code": code, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not row:
        return None
    # Honor both field-name variants (legacy divergence noted in the
    # TE-portal-job recon). If either explicitly disables the row,
    # treat as inactive.
    if row.get("is_active") is False or row.get("active") is False:
        return None
    return row


# ═══════════════════════════════════════════════════════════════════
# Phase EMAIL-MIGRATE · Feb-2026 — Global-default fallback lookup.
# ═══════════════════════════════════════════════════════════════════
async def get_template_with_global_fallback(
    code: str, tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the ``marketing_templates`` row for ``code``, preferring
    a tenant-specific row (``tenant_id`` matches) over the global
    default (``tenant_id: None``).

    Mirrors the door-hanger cascade shipped in
    ``routers.workstream_service_log._build_door_hanger_email``:

    * Tenant-specific row wins over the global default.
    * A row with an explicit ``is_active=False`` / ``active=False`` is
      treated as absent so a tenant can disable a template without
      deleting the row.
    * ``tenant_id=None`` (or ``""``) is legal — callers use it to
      probe the global default in flows that don't have a tenant
      (e.g. very early signup states before the tenant is fully
      provisioned).

    Returns ``None`` when no active row exists for that ``code``.
    """
    if not code:
        return None
    tenant_filter: List[Dict[str, Any]] = [
        {"tenant_id": None},
        {"tenant_id": {"$exists": False}},
    ]
    if tenant_id:
        tenant_filter.insert(0, {"tenant_id": tenant_id})
    row = await config.db.marketing_templates.find_one(
        {"code": code, "$or": tenant_filter},
        {"_id": 0},
        # ``sort=[("tenant_id", -1)]`` places non-null tenant_id
        # strings ahead of ``None`` so the tenant-specific row wins
        # when both a tenant row + the global default exist.
        sort=[("tenant_id", -1)],
    )
    if not row:
        return None
    if row.get("is_active") is False or row.get("active") is False:
        return None
    return row
