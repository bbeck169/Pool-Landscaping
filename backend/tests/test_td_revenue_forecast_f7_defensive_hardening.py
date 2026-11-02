"""TD-revenue-forecast-f7-defensive-hardening · Nov-2026 — regression
suite.

Locks the F7-first per-job value cascade inside the BOOKED branch of
``GET /admin/dashboard/revenue-forecast`` at
``backend/routers/dashboard_revenue.py:605-650`` (post-ticket line
range).

Pre-ticket cascade:   ``price → total → quote_total``.
Post-ticket cascade:  ``line_items.sum → price → total → quote_total``.

The F7 branch mirrors ``auto_invoice._build_line_items`` at
``services/auto_invoice.py:60-104`` — ``line_total_cents = round(qty *
unit_price * 100)``, summed across lines, converted back to dollars.
The two code paths MUST stay in lock-step so a job that F7-auto-
invoices for $140 also forecasts for $140.

PREVIEW-OBSERVABLE EFFECT: None.  Phase 0.5 recon confirmed the F7
cohort (``price=0 or missing`` AND non-empty ``line_items[]``) has
count 0 in the preview DB (``count_documents`` ran against
``affdfbfa-88b9-4baa-ae45-2ef78531b6e4`` which carries 8,649 of
9,605 total preview jobs).  This suite seeds the cohort explicitly
via ``_f7_loop_fixture.run_test`` so the invariants are locked
regardless of preview-DB contents.

Assertions (brief's seven cases + three regression locks):

  Case 1 · F7 job rescue:
    ``price=0``, ``line_items=[{unit:50,qty:2},{unit:40,qty:1}]``
    → BOOKED sum includes +$140.
  Case 2 · F7 zero-line still skipped:
    ``price=0``, ``line_items=[{unit:0,qty:1}]`` → NOT counted
    (preserves the zero-price guard).
  Case 3 · Legacy flat-price unchanged:
    ``price=165``, ``line_items=[]`` → BOOKED sum includes +$165.
  Case 4 · No double-count when both populated:
    ``price=200``, ``line_items=[{unit:50,qty:2}]`` → BOOKED sum
    includes +$100 (F7 wins, flat-price NOT also added).
  Case 5 · No-pricing shell still skipped:
    ``price=0``, ``line_items=[]`` → NOT counted (zero-price guard).
  Case 6 · Tenant isolation:
    Cross-tenant F7 job → NOT counted (sanity on tenant filter).
  Case 7 · Status filter:
    F7 job with ``status="completed"`` → NOT counted (locks the
    shipped forward-only status filter).
  Case 8 · Date window:
    F7 job scheduled outside the window → NOT counted (locks the
    scheduled_date gate).
  Case 9 · Qty-0 line still contributes nothing:
    ``price=0``, ``line_items=[{unit:999,qty:0}]`` → NOT counted
    (F7 sum = 0 falls through to zero-price guard).
  Case 10 · F7 fractional qty + rounding parity with auto_invoice:
    ``price=0``, ``line_items=[{unit:12.345,qty:3}]`` → BOOKED
    includes the auto-invoice-equivalent dollar amount (locks the
    cents-rounding formula lock-step with ``auto_invoice.py:60-104``).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from tests._f7_loop_fixture import run_test


async def _admin_ctx(db):
    tenant = await db.tenants.find_one(
        {"slug": "aquaterra"}, {"_id": 0, "id": 1},
    )
    tid = tenant["id"]
    admin = await db.users.find_one(
        {"email": "admin@aquaterra.com"},
        {"_id": 0, "id": 1, "role": 1},
    )
    return tid, admin


async def _cleanup(db, tid, prefix):
    await db.jobs.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )


def _window(target: date):
    """BOOKED filter runs against ``scheduled_date >= start[:10]`` and
    ``<= end`` — pass a 1-day window matching the target date."""
    return (f"{target.isoformat()}T00:00:00",
             f"{target.isoformat()}T23:59:59")


def test_f7_defensive_hardening_eight_shapes():
    """Compact end-to-end suite — seeds all shapes in one tenant +
    one call, asserts the final ``booked.amount`` matches the
    expected sum of the shapes that SHOULD contribute."""
    from routers.dashboard_revenue import revenue_forecast

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = f"F7HARD_{uuid.uuid4().hex[:6]}_"
        await _cleanup(db, tid, prefix)
        target = date.today() + timedelta(days=3)
        other  = target + timedelta(days=5)      # out of window
        s_iso, e_iso = _window(target)

        shapes = [
            # Case 1 — F7 rescue: sum = 2*50 + 1*40 = $140.
            {"id": f"{prefix}f7_rescue", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": target.isoformat(),
             "price": 0,
             "line_items": [
                 {"unit_price": 50, "quantity": 2},
                 {"unit_price": 40, "quantity": 1},
             ]},
            # Case 2 — F7 zero-line: NOT counted.
            {"id": f"{prefix}f7_zero", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": target.isoformat(),
             "price": 0,
             "line_items": [{"unit_price": 0, "quantity": 1}]},
            # Case 3 — Legacy flat-price unchanged: $165.
            {"id": f"{prefix}flat_price", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": target.isoformat(),
             "price": 165, "line_items": []},
            # Case 4 — Both populated: F7 wins ($100), flat-price
            # ignored.  Had we double-counted this would land at
            # $300 (= 200 + 100).
            {"id": f"{prefix}both", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": target.isoformat(),
             "price": 200,
             "line_items": [{"unit_price": 50, "quantity": 2}]},
            # Case 5 — No pricing shell: NOT counted.
            {"id": f"{prefix}shell", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": target.isoformat(),
             "price": 0, "line_items": []},
            # Case 7 — Status=completed: NOT counted (not in the
            # forward-looking status set).
            {"id": f"{prefix}completed", "tenant_id": tid,
             "status": "completed",
             "scheduled_date": target.isoformat(),
             "price": 0,
             "line_items": [{"unit_price": 999, "quantity": 1}]},
            # Case 8 — Out of window: NOT counted.
            {"id": f"{prefix}out_of_window", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": other.isoformat(),
             "price": 0,
             "line_items": [{"unit_price": 777, "quantity": 1}]},
            # Case 9 — qty=0: NOT counted (F7 sum = 0).
            {"id": f"{prefix}qty_zero", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": target.isoformat(),
             "price": 0,
             "line_items": [{"unit_price": 999, "quantity": 0}]},
            # Case 10 — Fractional qty + rounding parity: 3 * 12.345
            # = 37.035 dollars → auto-invoice converts per-line to
            # cents (round(3*12.345*100) = 3704 cents → $37.04).
            # Forecast MUST match the auto-invoice formula.
            {"id": f"{prefix}fractional", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": target.isoformat(),
             "price": 0,
             "line_items": [{"unit_price": 12.345, "quantity": 3}]},
        ]
        await db.jobs.insert_many(shapes)

        # Case 6 — Cross-tenant: another tenant's F7 job must NOT
        # contribute to this tenant's forecast.  Pick any tenant
        # id that is NOT ours — a synthetic one is sufficient
        # because the forecast query uses ``tenant_id == tid``.
        other_tid = f"NOT_{tid}"
        await db.jobs.insert_one({
            "id": f"{prefix}cross_tenant", "tenant_id": other_tid,
            "status": "scheduled",
            "scheduled_date": target.isoformat(),
            "price": 0,
            "line_items": [{"unit_price": 500, "quantity": 1}],
        })

        try:
            result = await revenue_forecast(
                start=s_iso, end=e_iso,
                user={**admin, "tenant_id": tid},
                tenant={"id": tid},
            )

            # Case 10: 3 * 12.345 = 37.035 → round(3 * 12.345 * 100)
            # = round(3703.5) = 3704 cents → $37.04 (Python banker's
            # rounding on .5 → nearest even).  Mirror the formula
            # inline so the test is self-explanatory about which
            # rounding behavior is locked.
            case10 = round(3 * 12.345 * 100) / 100.0
            expected_booked = 140.0 + 165.0 + 100.0 + case10

            actual_booked = result["booked"]["amount"]
            assert abs(actual_booked - expected_booked) < 0.01, (
                f"BOOKED mismatch — expected={expected_booked:.2f} "
                f"actual={actual_booked:.2f}.  Shapes contributing "
                f"should be: f7_rescue($140), flat_price($165), "
                f"both($100 via F7), fractional(${case10:.2f}).  "
                f"Shapes NOT contributing: f7_zero, shell, "
                f"completed, out_of_window, qty_zero, cross_tenant."
            )

            # And the booked count should match (4 contributing).
            assert result["booked"]["job_count"] == 4, (
                f"booked_count expected=4 "
                f"actual={result['booked']['job_count']}"
            )
        finally:
            await _cleanup(db, tid, prefix)
            await db.jobs.delete_many(
                {"tenant_id": other_tid,
                 "id": {"$regex": f"^{prefix}"}},
            )

    run_test(_go)


def test_f7_formula_matches_auto_invoice_build_line_items():
    """Static invariant: the forecast's F7 formula is byte-
    equivalent to ``auto_invoice._build_line_items``'s per-line
    computation.  If auto_invoice changes to e.g. floor instead of
    round, this test fails and signals the forecast must track.
    """
    import re
    forecast_src = open(
        "/app/backend/routers/dashboard_revenue.py", "r",
    ).read()
    autoinv_src = open(
        "/app/backend/services/auto_invoice.py", "r",
    ).read()
    # The forecast carries the same ``round(qty * unit * 100)``
    # cents formula as auto_invoice:60-104.
    assert re.search(
        r"int\(round\(qty\s*\*\s*unit_dollars\s*\*\s*100\)\)",
        forecast_src,
    ), "forecast F7 cents formula missing / drifted"
    assert re.search(
        r"int\(round\(qty\s*\*\s*unit_dollars\s*\*\s*100\)\)",
        autoinv_src,
    ), "auto_invoice F7 cents formula missing / drifted"
