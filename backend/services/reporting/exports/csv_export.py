"""Phase R1 · Feb-2026 — CSV export helper for reporting metrics.

Small, dependency-free CSV serializer that produces a bytes body
suitable for a FastAPI ``Response(media_type="text/csv")``.

Design contract
---------------

Every R1 report has a shape one of:

* **Scalar** (``pnl_by_period`` etc.) — a single ``value``,
  ``prior_value``, ``delta_pct`` and optional ``sparkline``. The
  CSV renders as ``["Metric", "Period", "Value", "Prior", "Delta %"]``
  plus a sparkline table below.
* **Grouped** (``ar_aging``, ``revenue_by_service_type`` etc.) —
  ``rows`` with dict entries. The CSV renders as ``["Row #",
  <keys sorted>...]``.
* **Line-item** (``pnl_line_items``, ``unpaid_invoices``) — same
  as grouped but the caller passes an explicit column order.

Byte-order-mark prefix (``\\ufeff``) so Excel opens the file as
UTF-8 by default; ``csv.excel`` dialect so the delimiter is a
plain comma and quoting handles commas + newlines in cell values.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        # Preserve two-decimal precision on currency and delta_pct
        # without introducing scientific notation for large sums.
        return f"{v:.2f}"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _footer_lines(tenant_name: Optional[str],
                  filters_applied: Optional[Dict[str, Any]]) -> List[List[str]]:
    lines: List[List[str]] = []
    lines.append([])  # blank separator
    if tenant_name:
        lines.append(["Tenant", tenant_name])
    if filters_applied:
        for k in sorted(filters_applied.keys()):
            v = filters_applied[k]
            if v in (None, "", [], {}):
                continue
            lines.append([f"Filter · {k}", _stringify(v)])
    lines.append(["Generated at",
                  datetime.now(timezone.utc).isoformat(timespec="seconds")])
    lines.append(["Source",
                  "R1 Financial Suite · services.reporting"])
    return lines


def render_scalar_csv(*,
                      metric_label: str,
                      period_label: str,
                      period_start: str,
                      period_end: str,
                      value: float,
                      prior_value: float,
                      delta_pct: Optional[float],
                      sparkline: Optional[List[Dict[str, Any]]] = None,
                      tenant_name: Optional[str] = None,
                      filters_applied: Optional[Dict[str, Any]] = None,
                      ) -> bytes:
    """Render a scalar-metric envelope as CSV."""
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM for Excel
    w = csv.writer(buf, dialect="excel")
    w.writerow(["Metric", "Period", "Start", "End",
                "Value", "Prior", "Delta %"])
    w.writerow([
        metric_label, period_label, period_start, period_end,
        _stringify(value), _stringify(prior_value),
        _stringify(delta_pct),
    ])
    if sparkline:
        w.writerow([])
        w.writerow(["Sparkline point", "Bucket", "Value"])
        for i, pt in enumerate(sparkline, start=1):
            w.writerow([i, _stringify(pt.get("t")),
                        _stringify(pt.get("v"))])
    for line in _footer_lines(tenant_name, filters_applied):
        w.writerow(line)
    return buf.getvalue().encode("utf-8")


def render_rows_csv(*,
                    metric_label: str,
                    period_label: str,
                    period_start: str,
                    period_end: str,
                    columns: List[str],
                    rows: Iterable[Dict[str, Any]],
                    total: Optional[float] = None,
                    tenant_name: Optional[str] = None,
                    filters_applied: Optional[Dict[str, Any]] = None,
                    ) -> bytes:
    """Render a grouped/line-item envelope as CSV.

    ``columns`` is the ordered list of dict keys to include per
    row. Any missing key on a given row renders as empty. Extra
    keys on a row are ignored (not surfaced).
    """
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf, dialect="excel")
    w.writerow([metric_label])
    w.writerow(["Period", period_label, period_start, period_end])
    if total is not None:
        w.writerow(["Total", _stringify(total)])
    w.writerow([])
    # Header row — humanise the column keys for the header.
    w.writerow([_humanise(k) for k in columns])
    n = 0
    for row in rows:
        w.writerow([_stringify(row.get(k)) for k in columns])
        n += 1
    if n == 0:
        w.writerow(["(no rows)"])
    for line in _footer_lines(tenant_name, filters_applied):
        w.writerow(line)
    return buf.getvalue().encode("utf-8")


def _humanise(key: str) -> str:
    return key.replace("_", " ").title()
