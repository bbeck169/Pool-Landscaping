"""Feb-2026 · Homeworks Customer.discount schema-drift fix — pytest suite.

Homeworks removed the scalar ``discount`` field from the ``Customer`` type,
which surfaced as::

    GraphQL request failed with status 400:
      Cannot query field "discount" on type "Customer".

Both cohort queries dropped the selection. This suite pins the fix so a
future refactor can't silently re-introduce the field:

  1. ``CUSTOMER_PAGE_QUERY`` (inactive cohort) no longer selects ``discount``
     on the Customer body.
  2. ``ACTIVE_CUSTOMER_PAGE_QUERY`` (active cohort) ditto — Delta Sync shares
     both cohorts so this closes ``both_cohorts_failed_dry_run`` too.
  3. Invoice-level ``discountPercent`` / ``discountAmount`` remain — the
     fix was targeted to the Customer type, not a codebase sweep.
  4. Non-``discount`` fields the mapper depends on (``id``, ``fullName``,
     ``status``, ``customerType`` ...) are still requested — a regression
     against overreach.
  5. The MCP wrapper still raises a structured ``MCPError`` when Homeworks
     returns ``isError: true`` (the surface the dispatcher UI shows). Proves
     the failure path we relied on for observability is intact.
"""
from __future__ import annotations

import re

import pytest

from services.homeworks_mcp import queries as _q


_CUSTOMER_BODY_START = re.compile(r"\) \{\s*id\s*\n", re.MULTILINE)


def _customer_body(query_str: str) -> str:
    """Return the selection body between the outermost ``) { id`` opener and
    its matching closing brace pair.  We don't need a real GraphQL parser —
    the two Customer queries in this file follow an identical fixture shape.
    """
    m = _CUSTOMER_BODY_START.search(query_str)
    assert m, "customer body not found in query string"
    # Walk from ``id`` line to the matching closing brace of the Customer
    # selection set (two closes: one for the customer fields, one for the
    # customers(...) call itself). Return everything in between.
    start = m.start()
    depth = 0
    end = start
    for i, ch in enumerate(query_str[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                end = i
                break
    return query_str[start:end]


# ── 1. Inactive cohort — no ``discount`` on Customer ──────────────
def test_inactive_customer_query_drops_discount():
    body = _customer_body(_q.CUSTOMER_PAGE_QUERY)
    # A standalone ``discount`` selection line would render as either
    # "    discount\n" (indented) or "discount\n" at BOL. Neither may
    # appear on the Customer body.
    assert not re.search(r"(^|\n)\s*discount\s*(\n|$)", body), (
        "Customer.discount selection re-introduced in CUSTOMER_PAGE_QUERY — "
        "Homeworks removed the field, this will 400 on prod."
    )


# ── 2. Active cohort — same guard ─────────────────────────────────
def test_active_customer_query_drops_discount():
    body = _customer_body(_q.ACTIVE_CUSTOMER_PAGE_QUERY)
    assert not re.search(r"(^|\n)\s*discount\s*(\n|$)", body), (
        "Customer.discount selection re-introduced in ACTIVE_CUSTOMER_PAGE_QUERY."
    )


# ── 3. Estimate-level discount fields untouched ────────────────────
def test_estimate_discount_fields_still_selected():
    # ``discountPercent`` / ``discountAmount`` live on the Estimate type
    # (``CUSTOMER_ESTIMATES_QUERY``). The fix must NOT sweep them out —
    # only the Customer-type ``discount`` scalar was removed by Homeworks.
    est_q = getattr(_q, "CUSTOMER_ESTIMATES_QUERY", "")
    assert est_q, "CUSTOMER_ESTIMATES_QUERY missing — grep this test"
    assert "discountPercent" in est_q, "discountPercent must remain on Estimate"
    assert "discountAmount" in est_q, "discountAmount must remain on Estimate"


# ── 4. Mapper-critical fields still requested ─────────────────────
@pytest.mark.parametrize("query", [
    _q.CUSTOMER_PAGE_QUERY,
    _q.ACTIVE_CUSTOMER_PAGE_QUERY,
])
def test_mapper_critical_fields_still_selected(query):
    body = _customer_body(query)
    for field in ("id", "email", "fullName", "status", "customerType"):
        assert re.search(rf"(^|\n)\s*{re.escape(field)}\b", body), (
            f"{field} selection dropped from Customer query — the mapper "
            f"depends on it downstream."
        )


# ── 5. MCP wrapper still raises MCPError on isError payloads ──────
def test_mcp_wrapper_surfaces_tool_returned_iserror():
    """The wrapper's ``isError`` branch is what shows the UI banner.
    Verify the raise path with a synthetic ``discount`` schema error so a
    refactor of ``client.py`` can't silently swallow future schema drifts.
    """
    import asyncio
    from services.homeworks_mcp import client as _c

    class _FakeMCP:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_e): return False
        async def call_tool(self, name, args):
            # Exact shape Homeworks returned to the user (redacted).
            return {
                "content": [{
                    "type": "text",
                    "text": (
                        'GraphQL request failed with status 400: {"errors":'
                        '[{"message":"Cannot query field \\"discount\\" on '
                        'type \\"Customer\\".","locations":[{"line":25,'
                        '"column":5}],"extensions":{"code":'
                        '"GRAPHQL_VALIDATION_FAILED"}}]\n'
                    ),
                }],
                "isError": True,
            }

    orig = _c.HomeworksMCPClient
    _c.HomeworksMCPClient = _FakeMCP
    try:
        with pytest.raises(_c.MCPError) as ei:
            asyncio.get_event_loop().run_until_complete(
                _c.gql_query(
                    query=_q.CUSTOMER_PAGE_QUERY,
                    variables={"skip": 0, "take": 1},
                    tenant_id="t1", user_id="u1",
                ),
            )
        # Structured, greppable prefix — the dispatcher UI banner reads this.
        assert str(ei.value).startswith("tool_returned_isError:"), str(ei.value)
    finally:
        _c.HomeworksMCPClient = orig
