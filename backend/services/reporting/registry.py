"""Phase R0 · Feb-2026 — Metric registry for the reporting suite.

A "metric" is a small object with:

* ``key`` — stable snake_case identifier used in the URL and the
  cache key.  MUST be unique across the registry.
* ``label`` — human display string surfaced by the KPI card.
* ``format`` — one of ``"currency"``, ``"number"``, ``"percent"``
  so the frontend can render the value without duplicating the
  metric definition.
* ``direction`` — ``"up_is_good"`` | ``"down_is_good"``. Controls
  the green/red delta chip on ``<VarianceTile>``.
* ``compute(engine, period)`` — async callable returning
  ``{value, prior_value, delta_pct, sparkline}``.

Register a metric with the ``@register_metric`` decorator:

    @register_metric
    class RevenueTotal(Metric):
        key = "revenue_total"
        label = "Total Revenue"
        format = "currency"
        direction = "up_is_good"

        async def compute(self, engine, period): ...

R1–R7 phases will drop new files under ``services/reporting/metrics/``
and the registry auto-populates on first import via
``services.reporting.__init__``.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException


VALID_FORMATS = ("currency", "number", "percent")
VALID_DIRECTIONS = ("up_is_good", "down_is_good")


class Metric:
    """Base class for a KPI. Subclasses set class attributes
    ``key``, ``label``, ``format``, ``direction`` and implement
    ``compute(engine, period)``. Using plain class attributes
    (not dataclass fields) so ``@register_metric`` can instantiate
    each subclass with a bare no-arg constructor while still
    inheriting the parent defaults.

    Phase R0.1 · Feb-2026 — ``is_grouped=True`` metrics emit a
    ``{total, rows, lens, filters_applied}`` envelope instead of
    the scalar ``{value, prior_value, delta_pct, sparkline}``
    envelope. Router dispatches on this flag.
    """

    key: str = ""
    label: str = ""
    format: str = "number"
    direction: str = "up_is_good"
    description: str = ""
    is_grouped: bool = False   # R0.1 · flip on for group-by metrics

    async def compute(self, engine, period) -> dict:
        """Override in subclasses. Must return a dict with at least
        ``value`` and ``prior_value`` (floats) and optionally
        ``delta_pct`` (float | None) and ``sparkline`` (list of
        ``{t, v}``).  If ``delta_pct`` is missing, the router
        computes it as ``(value - prior_value) / prior_value``.
        """
        raise NotImplementedError

    async def compute_grouped(self, engine, period, filters: dict) -> dict:
        """R0.1 hook — grouped metrics override THIS instead of
        ``compute``. Must return ``{total, rows, ...}``. ``filters``
        is a caller-owned dict of already-normalized query params
        (``lens``, ``service_type``, ``tech_id``, ``limit``,
        ``offset``). Never called on scalar metrics."""
        raise NotImplementedError

    # Convenience for consumers that just want a dict.
    def to_public(self) -> dict:
        return {"key": self.key, "label": self.label,
                "format": self.format, "direction": self.direction,
                "description": self.description,
                "is_grouped": self.is_grouped}


REGISTRY: dict[str, Metric] = {}


def register_metric(metric_cls):
    """Decorator: instantiate the class and add it to the registry."""
    if not isinstance(metric_cls, type):
        raise TypeError("register_metric expects a class")
    instance: Metric = metric_cls()  # type: ignore[call-arg]
    if not instance.key:
        raise ValueError(f"{metric_cls.__name__} must define a non-empty key")
    if instance.format not in VALID_FORMATS:
        raise ValueError(
            f"{metric_cls.__name__}: format must be one of {VALID_FORMATS}"
        )
    if instance.direction not in VALID_DIRECTIONS:
        raise ValueError(
            f"{metric_cls.__name__}: direction must be one of {VALID_DIRECTIONS}"
        )
    if instance.key in REGISTRY:
        raise ValueError(f"duplicate metric key: {instance.key}")
    REGISTRY[instance.key] = instance
    return metric_cls


def get_metric(key: str) -> Metric:
    m = REGISTRY.get(key)
    if not m:
        raise HTTPException(404, f"Unknown metric: {key}")
    return m
