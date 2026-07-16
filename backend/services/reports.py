"""Phase 55.1 · Reporting helpers used by the AI CFO digest + pricing
insights table.

* ``stripe_cash_weekly(tenant_id, month)`` — aggregates the weekly
  net cash collected via Stripe for a given ``YYYY-MM``. Buckets by
  ISO week starting Monday. Excludes rows with ``status`` in
  (``failed``, ``initiated``, ``processing``) so only actually
  captured / refunded payments contribute.

Amounts are always integer cents. Timestamps are our own
``updated_at`` on the ledger row (which is when the payment was
applied) — we deliberately do NOT use Stripe's raw ``created`` because
it drifts across retries + refunds.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import db


def _parse_month(month: Optional[str]) -> tuple[date, date]:
    """Return (inclusive_start, exclusive_end) for a ``YYYY-MM`` string.
    Defaults to the previous calendar month (aligned with the digest cron)."""
    now = datetime.now(timezone.utc)
    if month:
        try:
            y, m = [int(x) for x in month.split("-", 1)]
        except Exception:
            y, m = now.year, now.month
    else:
        y = now.year if now.month > 1 else now.year - 1
        m = now.month - 1 if now.month > 1 else 12
    start = date(y, m, 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = date(ny, nm, 1)
    return start, end


def _week_start(d: date) -> date:
    """Monday of the ISO week containing ``d``."""
    return d - timedelta(days=d.weekday())


async def stripe_cash_weekly(tenant_id: str, month: Optional[str] = None) -> list[dict]:
    """List of ``{week_starting, cash_collected_cents, refunds_cents, net_cents}``.

    Weeks with zero activity are omitted. Rows are sorted ascending.
    """
    start, end = _parse_month(month)
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    rows = await db.stripe_payments.find(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["paid", "refunded"]},
            "updated_at": {"$gte": start_iso, "$lt": end_iso},
        },
        {"_id": 0, "updated_at": 1, "amount_cents": 1, "refunded_cents": 1},
    ).to_list(5000)

    buckets: dict[date, dict] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat((r.get("updated_at") or "").replace("Z", "+00:00")).date()
        except Exception:
            continue
        wk = _week_start(d)
        b = buckets.setdefault(wk, {"cash_collected_cents": 0, "refunds_cents": 0})
        b["cash_collected_cents"] += int(r.get("amount_cents") or 0)
        b["refunds_cents"] += int(r.get("refunded_cents") or 0)

    out: list[dict] = []
    for wk in sorted(buckets):
        b = buckets[wk]
        out.append({
            "week_starting": wk.isoformat(),
            "cash_collected_cents": b["cash_collected_cents"],
            "refunds_cents": b["refunds_cents"],
            "net_cents": b["cash_collected_cents"] - b["refunds_cents"],
        })
    return out
