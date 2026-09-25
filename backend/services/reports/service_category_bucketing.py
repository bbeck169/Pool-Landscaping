"""Shared service-category bucketing for the dashboard revenue + drill-down.

Feb-2026 · Task · Income by Service Category drill-down parity.

Before this module the chart route (``routers.dashboard_revenue
.income_by_service_category``) and the drill-down route (``routers
.dashboard_drilldown.income_by_service_rows``) each carried their
own inline resolution ladder for mapping a paid-invoice line item
to a service-category bucket.  The two implementations drifted:

  * Chart routed a line whose ``service_category_id`` was
    truthy-but-stale (i.e. no ``svc_id_to_name`` hit) into
    ``"Uncategorized"`` via ``bucket_key = svc_name or "Uncategorized"``.
  * Drill-down explicitly filtered the same line out with the check
    ``if svc_id is not None and svc_name != "Uncategorized": continue``.

Result: chart totals under the Uncategorized bucket were bigger
than the drill-down list totals for that bucket.

This module extracts the ladder into one pure function so both
routes call the same code path.  The chart continues to emit
buckets keyed by *name* (unchanged public output).  The drill-down
now switches to matching on the *bucket_id* returned here so a
stale ``service_category_id`` on a line rolls up to the sentinel
``__uncategorized__`` bucket on both sides.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# Match the sentinel already used by ``routers.profit_report`` and
# ``routers.pricebook_supplier_spend`` so the whole reporting
# surface shares one Uncategorized key.
UNCATEGORIZED_KEY: str = "__uncategorized__"
UNCATEGORIZED_NAME: str = "Uncategorized"


def bucket_service_category(
    line_item: Dict[str, Any],
    item_to_svc: Dict[str, str],
    svc_id_to_name: Dict[str, str],
) -> Tuple[str, str]:
    """Bucket a paid-invoice line item into a service category.

    Resolution ladder (mirrors ``dashboard_revenue.py:411-418`` /
    P53 precedence):

    1. Line-item's own ``service_category_id`` (user explicitly
       recategorised this line — overrides all).
    2. Pricebook item's ``service_category_id`` via
       ``item_to_svc[line_item["item_id"]]`` (default inherited).
    3. If the resolved id has no name in ``svc_id_to_name`` (stale /
       deleted category, or empty), the line falls into the
       ``UNCATEGORIZED_KEY`` bucket.
    4. If neither the line nor the pricebook item yields an id at
       all, the line falls into the ``UNCATEGORIZED_KEY`` bucket.

    Returns
    -------
    (bucket_id, bucket_name) :
        ``bucket_id`` is a real ``service_categories.id`` when
        resolvable, else ``UNCATEGORIZED_KEY``.
        ``bucket_name`` is the display name from
        ``svc_id_to_name`` when resolvable, else
        ``UNCATEGORIZED_NAME``.
    """
    line_svc_id = line_item.get("service_category_id")
    if line_svc_id:
        svc_id: Optional[str] = line_svc_id
    else:
        iid = line_item.get("item_id")
        svc_id = item_to_svc.get(iid) if iid else None

    if svc_id:
        name = svc_id_to_name.get(svc_id)
        if name:
            return svc_id, name

    return UNCATEGORIZED_KEY, UNCATEGORIZED_NAME
