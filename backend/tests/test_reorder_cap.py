"""Feb-2026 · P1 — Numbered Reorder cap (backend parity with web's MAX_ORDER_VALUE=50).

Three targeted assertions on the ``ReorderBody`` Pydantic model in
``routers/schedule_reorder.py``:

  * 12 ids validate cleanly (was never rejected pre-cap, still isn't).
  * 50 ids validate cleanly (the exact ceiling).
  * 51 ids reject with a Pydantic ``ValidationError`` — surfaces as
    422 at the FastAPI boundary; test against the model directly so
    the assertion doesn't depend on a booted app or auth headers.

The model is the single source of truth for both ``ordered_job_ids``
and legacy ``job_ids`` payload shapes, so both list fields are pinned
to ``max_length=50`` and both are exercised here.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from routers.schedule_reorder import ReorderBody


def _ids(n: int) -> list[str]:
    return [f"TEST_reorder_{i}" for i in range(n)]


@pytest.mark.parametrize("field", ["ordered_job_ids", "job_ids"])
def test_reorder_accepts_12_ids(field):
    body = ReorderBody(**{field: _ids(12), "tech_user_id": "u1", "date": "2026-05-01"})
    assert len(getattr(body, field) or []) == 12


@pytest.mark.parametrize("field", ["ordered_job_ids", "job_ids"])
def test_reorder_accepts_50_ids_at_the_ceiling(field):
    body = ReorderBody(**{field: _ids(50), "tech_user_id": "u1", "date": "2026-05-01"})
    assert len(getattr(body, field) or []) == 50


@pytest.mark.parametrize("field", ["ordered_job_ids", "job_ids"])
def test_reorder_rejects_51_ids(field):
    with pytest.raises(ValidationError) as ei:
        ReorderBody(**{field: _ids(51), "tech_user_id": "u1", "date": "2026-05-01"})
    # Pydantic v2 surfaces list overflow as ``too_long`` on the field.
    assert any(
        (e.get("type") in ("too_long", "list_too_long")
         or "at most 50" in str(e).lower())
        for e in ei.value.errors()
    ), ei.value.errors()
