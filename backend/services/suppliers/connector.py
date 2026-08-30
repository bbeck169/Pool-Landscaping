"""Phase 54a · Feb-2026 — Supplier connector protocol + stubs.

Every concrete connector (PoolCorp / SiteOne / Ewing / Heritage /
ePoolSupply) implements ``SupplierConnector``. In Phase 54a all five
concrete classes raise ``NotImplementedError`` on both abstract
methods — the wire-up happens in the per-supplier phases 54b/c/d/e.

The protocol enforces a stable ExternalProduct shape (tier 6B fields
per the user's locked scope) so downstream sync code can be written
once + shared across every connector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Protocol


@dataclass
class ExternalProduct:
    """Tier-6B field set locked by the user for Phase 54a."""
    sku: str
    name: str
    cost: Optional[float] = None
    msrp: Optional[float] = None
    category: Optional[str] = None
    uom: Optional[str] = None       # unit-of-measure (each / box / gallon / …)
    description: Optional[str] = None
    # Raw supplier payload preserved for future field extraction
    # without a schema migration.
    raw: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# Shared connector exception classes.
#
# Phase O4 · Feb-2026 — moved from ``services/suppliers/poolcorp.py``
# so every sibling connector (SiteOne / Ewing / Heritage /
# ePoolSupply) can raise + catch them without having to import from
# ``poolcorp`` (which is what the pre-move code-review flagged as a
# supplier-directory circular-import smell).  ``poolcorp.py``
# still re-exports these names for backward compat so existing
# ``from services.suppliers.poolcorp import LoginFailedError`` call
# sites in ``sync.py``, ``_scraper_base.py``, ``ewing.py``,
# ``siteone.py``, and the supplier-cron tests keep working
# unchanged.
# ═══════════════════════════════════════════════════════════════════
class LoginFailedError(Exception):
    """Raised when a supplier login flow rejects the credentials.
    Every connector's ``authenticate`` raises this on bad-cred
    outcomes; ``sync.py`` catches it and stamps the failure reason
    on ``supplier_sync_runs.error_reason``."""


class LayoutChangedError(Exception):
    """Raised when a supplier's product-listing page returns zero
    cards — likely a site layout change or a silent credential
    expiry. NEVER treated as 'delete all items'; the sync aborts
    with this error so ops can investigate before catalog drift
    corrupts the price book."""


@dataclass
class SupplierSession:
    """Opaque handle a connector's ``authenticate`` returns and its
    ``list_products`` consumes. Concrete connectors subclass or wrap
    whatever session primitive they need (``requests.Session``,
    HTTP client, cookie jar, …)."""
    supplier_slug: str
    credentials_ref: str  # supplier_credentials.id — never plaintext
    extra: Dict[str, Any] = field(default_factory=dict)


class SupplierConnector(Protocol):
    """Structural protocol every supplier connector implements."""

    slug: str
    display_name: str

    def authenticate(self, credentials: Dict[str, Any]) -> SupplierSession: ...

    def list_products(
        self,
        session: SupplierSession,
        since: Optional[str] = None,
    ) -> Iterable[ExternalProduct]: ...


class BaseSupplierConnector:
    """Concrete base class used by the five 54a stubs. Provides the
    NotImplementedError plumbing so a caller in a future phase gets a
    consistent error message pointing to the phase that owns it."""
    slug: str = ""
    display_name: str = ""
    planned_phase: str = ""
    # Phase 54h-a · Aug-2026 — default OFF for the Cloudflare Turnstile
    # handoff modal. Only Pool360 / SiteOne / Heritage opt in
    # (SUPPORTS_CHALLENGE_HANDOFF = True on those subclasses).
    SUPPORTS_CHALLENGE_HANDOFF: bool = False

    def _not_yet(self, method: str) -> "None":
        raise NotImplementedError(
            f"{self.display_name} connector.{method}() is not implemented "
            f"yet — planned for Phase {self.planned_phase}. Phase 54a is "
            f"the skeleton phase; no supplier network calls yet.")

    def authenticate(self, credentials: Dict[str, Any]) -> SupplierSession:
        self._not_yet("authenticate")

    def list_products(
        self,
        session: SupplierSession,
        since: Optional[str] = None,
    ) -> Iterable[ExternalProduct]:
        self._not_yet("list_products")


# ═══════════════════════════════════════════════════════════════════
# Concrete stubs — all NotImplementedError until their phase
# ═══════════════════════════════════════════════════════════════════
class PoolCorpConnector(BaseSupplierConnector):
    slug = "poolcorp"
    display_name = "Pool360 (PoolCorp)"
    planned_phase = "54b"


class SiteOneConnector(BaseSupplierConnector):
    slug = "siteone"
    display_name = "SiteOne"
    planned_phase = "54c"


class EwingConnector(BaseSupplierConnector):
    slug = "ewing"
    display_name = "Ewing Irrigation"
    planned_phase = "54d"


class HeritageConnector(BaseSupplierConnector):
    slug = "heritage"
    display_name = "Heritage Pool Plus"
    planned_phase = "54e"


class EPoolSupplyConnector(BaseSupplierConnector):
    slug = "epoolsupply"
    display_name = "ePoolSupply"
    planned_phase = "54e"


CONNECTORS: Dict[str, BaseSupplierConnector] = {
    c.slug: c() for c in (
        PoolCorpConnector, SiteOneConnector, EwingConnector,
        HeritageConnector, EPoolSupplyConnector,
    )
}


# ═══════════════════════════════════════════════════════════════════
# Wired connectors — replace the stub instances above as each phase
# lands. Import guarded with try/except so ``connector.py`` remains
# importable in a fresh checkout that hasn't installed Playwright
# yet (the wired connector modules import ``playwright.async_api``).
#
# Phase O4 · Feb-2026 code-review note — the code review flagged
# these ``try``/``except`` blocks as "in-function cycle-breaking
# import hacks" and suggested deleting them. They are NEITHER:
#   1. Module-level (not in-function) — they run once at boot.
#   2. Optional-dependency guards, NOT cycle-breakers. Deleting
#      them makes ``connector.py`` fail to import in any env that
#      hasn't installed Playwright (CI unit test containers, docs
#      generation, IDE indexers) — a real regression.
#   3. The sibling-directory cycle they help mitigate as a bonus
#      side-effect is separately addressed by moving
#      ``LoginFailedError`` / ``LayoutChangedError`` to this file
#      (Phase O4 · Feb-2026). Reviewers may re-open this once
#      Playwright is a mandatory prod dep. Not now.
# ═══════════════════════════════════════════════════════════════════
try:  # Phase 54b — Pool360 wired
    from services.suppliers.poolcorp import (  # noqa: E402
        PoolCorpConnector as _WiredPoolCorp,
    )
    CONNECTORS["poolcorp"] = _WiredPoolCorp()
except Exception:  # pragma: no cover — deps missing at import
    pass

try:  # Phase 54c — SiteOne wired
    from services.suppliers.siteone import (  # noqa: E402
        SiteOneConnector as _WiredSiteOne,
    )
    CONNECTORS["siteone"] = _WiredSiteOne()
except Exception:  # pragma: no cover — deps missing at import
    pass

try:  # Phase 54d — Ewing wired
    from services.suppliers.ewing import (  # noqa: E402
        EwingConnector as _WiredEwing,
    )
    CONNECTORS["ewing"] = _WiredEwing()
except Exception:  # pragma: no cover
    pass

try:  # Phase 54e — Heritage wired
    from services.suppliers.heritage import (  # noqa: E402
        HeritageConnector as _WiredHeritage,
    )
    CONNECTORS["heritage"] = _WiredHeritage()
except Exception:  # pragma: no cover
    pass

try:  # Phase 54e — ePoolSupply wired
    from services.suppliers.epoolsupply import (  # noqa: E402
        EPoolSupplyConnector as _WiredEPS,
    )
    CONNECTORS["epoolsupply"] = _WiredEPS()
except Exception:  # pragma: no cover
    pass


# The canonical seed set. Order preserved so ``GET /api/suppliers``
# always returns the same admin-facing default sort.
SUPPLIER_SEED: list[Dict[str, Any]] = [
    {"slug": "poolcorp",    "display_name": "Pool360 (PoolCorp)"},
    {"slug": "siteone",     "display_name": "SiteOne"},
    {"slug": "ewing",       "display_name": "Ewing Irrigation"},
    {"slug": "heritage",    "display_name": "Heritage Pool Plus"},
    {"slug": "epoolsupply", "display_name": "ePoolSupply"},
]
