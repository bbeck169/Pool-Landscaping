"""Phase R0 · Feb-2026 — Built-in metrics.

R0 ships exactly ONE metric (``revenue_total``) end-to-end as the
proof-point for the aggregation → cache → registry → router →
KpiCard pipeline. R1 will layer additional metrics into this
package without touching anything else.
"""
from . import revenue_total  # noqa: F401 — side-effect: registers metric
