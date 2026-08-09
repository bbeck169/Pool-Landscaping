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
except Exception:  # pragma: no cover — deps missing at import
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
