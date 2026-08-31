"""PERF-1 · Feb-2026 — Production-tenant filter helper.

Purpose
-------
Pre-serve boot stages iterate ``db.tenants.find({})``, which on this
workspace fans out over **486** tenants — of which **~66% are CI
fixtures** (slugs like ``TEST_``, ``srec-``, ``cra-``, ``jca-``,
``csv-``, ``p18-``, ``p26-``, ``ltcb-``, ``stage3iso-``).  Full-scan
per-tenant work in these stages (walkie channel bootstrap, customer
category denorm, multi-tos seed, marketing seeds, chemical seeds…)
adds significant boot latency and is provably pointless for the
fixture tenants — they either get purged shortly after their CI job
or exist purely for isolation and never see production traffic.

This module centralises the "is this a real production tenant?"
question in ONE place so:
  1. New pre-serve stages get the filter for free by importing
     ``production_tenants_query()`` instead of ``{}``.
  2. When a new CI prefix lands, we update it here — not scattered
     across 8 boot files.
  3. The exclusion set is testable in isolation.

Non-scope
---------
* The F3 startup integrity check **MUST NOT** use this filter — it
  must scan ALL tenants for dangling refs.  See
  ``services/startup/integrity_check.py`` — that module deliberately
  does not import from here.
* Post-serve background stages (data-repair, cleanup migrations,
  admin scripts) also do NOT use this filter — they need visibility
  into every tenant for maintenance semantics.
* This is not a data cleanup — test-fixture tenants remain in the
  DB and are addressable via direct-key lookup.  Only the "iterate
  everything" boot stages skip them.
"""
from __future__ import annotations

import re
from typing import Any, Dict

# ─── Substring prefixes that identify CI / test-fixture tenants ───
#
# Extended Feb-2026 based on live workspace data.  Each entry is a
# regex-safe prefix that appears on tenants created by CI or manual
# test runs.  When adding a new pattern, run:
#
#     >>> from services.tenants.production_tenants import (
#     ...     is_test_tenant_slug,
#     ... )
#     >>> is_test_tenant_slug("your-new-prefix-abc123")
#
# and confirm it returns True.  Then add a case to
# tests/test_perf1_production_tenants_filter.py.
TEST_TENANT_PREFIXES = (
    "TEST_",         # legacy python-side tests
    "test-",         # kebab-case tests
    "csv-",          # CSV import fixtures
    "csvb-",         # CSV batch import fixtures
    "jca-",          # JobsCategoryAudit fixtures
    "p18-",          # Phase 18 chemical usage fixtures
    "p22c-",         # Phase 22 fixtures
    "p26-",          # Phase 26 marketing-template fixtures
    "ptb-",          # Property-track-back fixtures
    "srec-",         # Service-record fixtures
    "cra-",          # Customer-refresh-audit fixtures
    "ltcb-",         # Late-completion backfill fixtures
    "stage3iso-",    # Stage-3 isolation fixtures
    "pp-test-",      # Product / pricing test fixtures
    "digest-",       # Digest-report fixtures
    "wc-test-",      # Widget-content test fixtures
    "stripe-b-",     # Stripe-backfill fixtures
    "stripe-e-",     # Stripe-event fixtures
    "perf-",         # perf-triad harnesses
    "cypress-",      # cypress e2e fixtures
    "e2e-",          # general e2e
    "fixture-",      # generic fixture
)


# Compiled once at module import — the Mongo `$regex` filter uses
# the ``|`` alternation of all prefixes, anchored with ``^``.  The
# equivalent Python-side check is compiled here for
# ``is_test_tenant_slug`` callers.
_TEST_TENANT_REGEX_STR = "|".join(
    "^" + re.escape(p) for p in TEST_TENANT_PREFIXES
)
_TEST_TENANT_REGEX = re.compile(_TEST_TENANT_REGEX_STR)


def is_test_tenant_slug(slug: str | None) -> bool:
    """Return True when ``slug`` matches a known CI-fixture prefix."""
    if not slug:
        return False
    return bool(_TEST_TENANT_REGEX.match(slug))


def production_tenants_query() -> Dict[str, Any]:
    """Return the Mongo filter that excludes CI-fixture tenants.

    Use in pre-serve boot loops::

        from services.tenants.production_tenants import (
            production_tenants_query,
        )

        async for t in db.tenants.find(
            production_tenants_query(),
            {"_id": 0, "id": 1},
        ):
            ...
    """
    return {
        "slug": {
            "$not": {"$regex": _TEST_TENANT_REGEX_STR},
        },
    }


__all__ = [
    "TEST_TENANT_PREFIXES",
    "is_test_tenant_slug",
    "production_tenants_query",
]
