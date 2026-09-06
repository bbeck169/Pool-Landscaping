"""Phase R0 · Feb-2026 — Built-in metrics.

R0 ships exactly ONE metric (``revenue_total``) end-to-end as the
proof-point for the aggregation → cache → registry → router →
KpiCard pipeline. R0.1 adds ``revenue_by_customer`` and
``revenue_by_city`` as the first grouped metrics; R1 will layer
additional metrics into this package without touching anything
else.
"""
from . import revenue_total  # noqa: F401 — side-effect: registers metric
from . import revenue_by_customer  # noqa: F401 — R0.1 grouped metric
from . import revenue_by_city  # noqa: F401 — R0.1 grouped metric

# Phase R1 · Feb-2026 — Financial Suite (7 new metrics).
from . import pnl_by_period  # noqa: F401 — R1 scalar
from . import pnl_line_items  # noqa: F401 — R1 grouped drill-down
from . import cashflow_by_period  # noqa: F401 — R1 grouped bucketed
from . import ar_aging  # noqa: F401 — R1 grouped bucketed
from . import ar_aging_by_customer  # noqa: F401 — R1 grouped drill-down
from . import revenue_by_service_type  # noqa: F401 — R1 grouped (K71 join)
from . import unpaid_invoices  # noqa: F401 — R1 grouped list
