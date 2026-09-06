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
