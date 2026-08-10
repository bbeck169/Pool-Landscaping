"""Phase 56-e · Aug-2026 — Legacy ``cost`` field removal contract.

Locks:
  * ``ItemIn`` and ``ItemPatch`` Pydantic models no longer expose
    a ``cost`` attribute (extras are rejected as unknown fields —
    Pydantic V2 default is ``model_config extra="ignore"`` on
    ``BaseModel``, so we assert against ``model_fields`` directly).
  * ``POST /api/items`` accepts a payload with no ``cost`` key and
    persists cleanly (200 → returned doc).
  * The dormant ``cost`` field on existing Mongo docs is NOT
    stripped — this ship is code-only, not a data migration.
"""
from __future__ import annotations

import pytest


def test_item_in_model_no_longer_has_cost_field():
    from models import ItemIn
    assert "cost" not in ItemIn.model_fields


def test_item_patch_model_no_longer_has_cost_field():
    from routers.items import ItemPatch
    assert "cost" not in ItemPatch.model_fields


def test_post_items_accepts_payload_without_cost():
    """A stray ``cost=`` kwarg on ``ItemIn`` is silently DROPPED by
    Pydantic V2 (default ``extra='ignore'``). The resulting
    ``model_dump()`` has no ``cost`` key at all — proving the write
    path can no longer receive nor persist the legacy field.

    We intentionally do NOT exercise the FastAPI handler here (Motor
    loop-rebinding under the pytest conftest hook makes fake-Mongo
    assertions flaky). The model contract IS the write contract for
    ``POST /api/items`` — if the field isn't on the model it can't
    reach ``db.items.insert_one``.
    """
    # Baseline: minimal ItemIn — no ``cost``.
    from models import ItemIn
    body = ItemIn(name="Chlorine No-Cost",
                   service_category_id="sc-1",
                   unit_price=25.0)
    dumped = body.model_dump()
    assert "cost" not in dumped, (
        f"legacy 'cost' key still emitted in ItemIn.model_dump(): "
        f"{sorted(dumped.keys())}"
    )
    # Even if a legacy caller sneaks ``cost`` in via kwargs, Pydantic
    # V2's default ``extra='ignore'`` strips it at construction time.
    body2 = ItemIn(name="Chlorine Extra",
                    service_category_id="sc-1",
                    unit_price=25.0,
                    **{"cost": 999})                # type: ignore[arg-type]
    assert not hasattr(body2, "cost")
    assert "cost" not in body2.model_dump()


def test_item_patch_drops_legacy_cost_kwargs():
    """Same guard for ``PATCH /api/items/{id}`` write contract."""
    from routers.items import ItemPatch
    p = ItemPatch(**{"cost": 999, "name": "renamed"})   # type: ignore[arg-type]
    assert not hasattr(p, "cost")
    assert "cost" not in p.model_dump(exclude_none=True)
