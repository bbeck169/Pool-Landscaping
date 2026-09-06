"""Phase R0 · Feb-2026 — Reporting suite foundation.

This package holds the tenant-scoped aggregation engine, the
metric registry, and the in-memory cache layer that R1–R7 will
hang additional KPIs off of.

Public surface:

    from services.reporting import (
        AggregationEngine,      # class · primitive aggregations
        REGISTRY,               # dict · metric_key → Metric instance
        Metric,                 # dataclass · shape of one KPI
        register_metric,        # decorator · add a metric to REGISTRY
        get_metric,             # helper · REGISTRY.get with 404-friendly err
        report_cache,           # singleton · TTL cache accessor
        Period,                 # dataclass · normalized start/end/label
        resolve_period,         # helper · MTD/QTD/YTD/last_30d/custom
    )

Importing this module IMPORTS the metrics package below it, which
in turn registers every built-in metric via the ``@register_metric``
decorator. This means the router only needs to import THIS module
to get the full registry populated.
"""
from .aggregation import AggregationEngine
from .cache import report_cache
from .period import Period, resolve_period
from .registry import (
    REGISTRY,
    Metric,
    get_metric,
    register_metric,
)

# Importing the metrics package triggers ``@register_metric``
# side-effects — every KPI file under ``metrics/`` registers itself
# on first import. Keep this after the registry re-exports so tests
# that patch ``REGISTRY`` don't race.
from . import metrics  # noqa: F401,E402

__all__ = [
    "AggregationEngine",
    "REGISTRY",
    "Metric",
    "get_metric",
    "register_metric",
    "report_cache",
    "Period",
    "resolve_period",
]
