"""PERF-1 · Feb-2026 — Production-tenants filter tests.

Pure-python tests on the helper — no DB, no HTTP.  Locks the vocab
and behavior in place so a future edit either (a) intentionally
updates both the helper and this test or (b) surfaces the drift in
CI.
"""
from __future__ import annotations

import re
import pytest

from services.tenants.production_tenants import (
    TEST_TENANT_PREFIXES,
    is_test_tenant_slug,
    production_tenants_query,
)


@pytest.mark.parametrize("slug,expected", [
    # ─── real production tenants — must NOT be filtered ───────
    ("aquaterra",                     False),
    ("acme-pools",                    False),
    ("Sunshine Landscaping",          False),
    ("landscape-pros",                False),
    ("crystal-blue-pools",            False),   # starts with 'cr' but not 'cra-'
    # ─── every prefix in TEST_TENANT_PREFIXES must match ─────
    ("TEST_abc",                      True),
    ("test-fixture-42",               True),
    ("csv-import-abc",                True),
    ("csvb-batch-1",                  True),
    ("jca-audit-xyz",                 True),
    ("p18-fixture",                   True),
    ("p22c-something",                True),
    ("p26-marketing",                 True),
    ("ptb-property-1",                True),
    ("srec-1",                        True),
    ("cra-refresh-1",                 True),
    ("ltcb-1",                        True),
    ("stage3iso-a",                   True),
    ("pp-test-price",                 True),
    ("digest-abc",                    True),
    ("wc-test-widget",                True),
    ("stripe-b-1",                    True),
    ("stripe-e-1",                    True),
    ("perf-harness-1",                True),
    ("cypress-e2e-x",                 True),
    ("e2e-full-suite",                True),
    ("fixture-x",                     True),
    # ─── edge cases ─────────────────────────────────────────
    ("",                              False),   # empty slug
    (None,                            False),   # None slug
    ("   ",                           False),   # whitespace-only
    # ─── prefix collisions the classifier must not fall for ─
    # ``testosterone-corp`` starts with ``test`` but not ``test-``.
    ("testosterone-corp",             False),
    # ``csvarial-inc`` starts with ``csv`` but not ``csv-`` or ``csvb-``.
    ("csvarial-inc",                  False),
    # ``performance-pools`` starts with ``perf`` but not ``perf-``.
    ("performance-pools",             False),
])
def test_is_test_tenant_slug_classifier(slug, expected):
    assert is_test_tenant_slug(slug) is expected


def test_production_tenants_query_shape():
    """The Mongo filter uses ``slug.$not.$regex`` so it's a drop-in
    replacement for ``{}`` on ``db.tenants.find({...})`` calls."""
    q = production_tenants_query()
    assert list(q.keys()) == ["slug"]
    assert list(q["slug"].keys()) == ["$not"]
    assert "$regex" in q["slug"]["$not"]
    # The regex must be a real regex string.
    pattern = q["slug"]["$not"]["$regex"]
    re.compile(pattern)   # raises if malformed


def test_production_tenants_query_regex_matches_python_helper():
    """The Python-side ``is_test_tenant_slug`` and the Mongo-side
    regex MUST be built from the same vocab.  Any drift is a bug —
    lock them together here."""
    pattern = production_tenants_query()["slug"]["$not"]["$regex"]
    py_regex = re.compile(pattern)
    for prefix in TEST_TENANT_PREFIXES:
        sample = prefix + "abc"
        assert py_regex.match(sample), (
            f"mongo regex missed prefix {prefix!r} — vocab drift"
        )
        assert is_test_tenant_slug(sample), (
            f"python helper missed prefix {prefix!r} — vocab drift"
        )


def test_vocab_is_the_documented_set():
    """Guardrail: any prefix add/remove must bump this test in
    lockstep so future contributors see the intent."""
    documented = {
        "TEST_", "test-", "csv-", "csvb-", "jca-", "p18-", "p22c-",
        "p26-", "ptb-", "srec-", "cra-", "ltcb-", "stage3iso-",
        "pp-test-", "digest-", "wc-test-", "stripe-b-", "stripe-e-",
        "perf-", "cypress-", "e2e-", "fixture-",
    }
    assert set(TEST_TENANT_PREFIXES) == documented
