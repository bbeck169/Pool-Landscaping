"""Feb-2026 · Ticket #2-REVERSAL — clear per-tenant DFS credentials.

Reverses the data footprint of Ticket #2 (per-tenant BYO DataForSEO
credentials, Sep-2026) by ``$unset``-ing the entire
``settings.integrations.dataforseo`` sub-document on every tenant.

Idempotent — safe to re-run indefinitely. A second run finds nothing
to unset and returns ``{"tenants_scanned": <n>, "docs_unset": 0}``.
The Fernet infrastructure in ``services/tenant_secrets_crypto.py``
is preserved for the future BYO framework; this migration only
touches persisted ciphertext.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("revert_tenant_dataforseo_credentials")


async def run_revert_tenant_dataforseo_credentials(db: Any) -> Dict[str, int]:
    """Return counts: ``{"tenants_scanned", "docs_unset"}``.

    ``tenants_scanned`` is the total tenant count. ``docs_unset`` is
    the number of tenants that actually had a DFS integration
    sub-document to clear (i.e. ``update_many.modified_count``).
    """
    tenants_scanned = await db.tenants.count_documents({})
    res = await db.tenants.update_many(
        {"settings.integrations.dataforseo": {"$exists": True}},
        {"$unset": {"settings.integrations.dataforseo": ""}},
    )
    logger.info(
        "[revert_tenant_dataforseo_credentials] "
        "tenants_scanned=%s docs_unset=%s",
        tenants_scanned, res.modified_count,
    )
    return {
        "tenants_scanned": tenants_scanned,
        "docs_unset": res.modified_count,
    }
