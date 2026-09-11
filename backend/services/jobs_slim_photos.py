"""Feb-2026 · Shared slim-photos row decorator.

Moved out of ``routers/jobs.py`` in the Feb-2026 slim-photos follow-up
so ``routers/customers.py`` (customer-detail embedded-jobs list) and
any future consumer can apply the same shape without duplicating the
loop.

Contract (matches ``routers/jobs.py`` list ship, Feb-2026):

  * ``photo_count`` — int, ``len(photos)`` (0 when the doc has no
    ``photos`` field or it's non-list).
  * ``photo_ids``  — list[str], stable per-photo ``id`` strings for
    lazy-loading via the existing per-photo GET.
  * Full ``photos`` array is dropped by default. Callers pass
    ``include_photos=True`` to restore the pre-slim shape (superset:
    ``photo_count`` + ``photo_ids`` are ALWAYS emitted regardless).

Legacy rows where the underlying Mongo doc has no ``photos`` key
are normalized to ``photo_count=0`` + ``photo_ids=[]`` so the
response shape is uniform across every row.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def slim_photos_on_rows(docs: Iterable[Dict[str, Any]],
                          include_photos: bool = False) -> List[Dict[str, Any]]:
    """Mutate + return ``docs`` in place with the slim-photos shape.
    Safe to call multiple times (idempotent). Returns the same list
    for chained-call ergonomics.
    """
    out: List[Dict[str, Any]] = list(docs) if not isinstance(docs, list) else docs
    for d in out:
        plist = d.get("photos") or []
        if not isinstance(plist, list):
            plist = []
        d["photo_count"] = len(plist)
        d["photo_ids"] = [
            str(p.get("id")) for p in plist
            if isinstance(p, dict) and p.get("id") is not None
        ]
        if include_photos:
            # Superset — keep the full ``photos`` array. Coerce
            # missing/null to ``[]`` so every row carries the key.
            d["photos"] = plist
        else:
            d.pop("photos", None)
    return out
