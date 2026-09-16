"""Phase CHK1 · Feb-2026 — pool checklist default optional items.

Locks the three new *optional* pool checklist items into every canonical
default list so they cannot be accidentally dropped by a future edit:

    1. "Emptied skimmer basket"
    2. "Emptied leaf canister"
    3. "Emptied Betta Skimmer"

Guarantees enforced by this suite:

* Each of the four canonical default lists contains all three items,
  in the exact casing/spacing used by the product brief.
* Items must be **optional** — never marked required, and never present
  in the chemistry gate's core / required-readings sets.
* Items may live in either dict form (``{"key", "label"}`` /
  ``{"id", "label", ...}``) or as plain strings. Whatever the shape,
  no ``required`` / ``mandatory`` flag may be set to a truthy value.
* Order is preserved: the three items appear as a contiguous appended
  block at the end of each list (guards against accidental interleave
  with the core seven pool items).
"""
from __future__ import annotations

from typing import Any, Iterable, List

import pytest

from routers.checklists import DEFAULT_POOL_ITEMS
from routers.document_generators import CANONICAL_POOL_CHECKLIST
from routers.jobs import POOL_CHECKLIST
from routers.service_reports import POOL_CHECKLIST_DEFAULT


NEW_ITEMS: List[str] = [
    "Emptied skimmer basket",
    "Emptied leaf canister",
    "Emptied Betta Skimmer",
]


def _label(item: Any) -> str:
    """Extract the human-facing label regardless of dict/string form."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        # Both {"key","label"} (checklists.py) and any future {"id","label"}
        # dicts expose the human label via "label".
        return str(item.get("label") or item.get("name") or "")
    return ""


def _labels(items: Iterable[Any]) -> List[str]:
    return [_label(x) for x in items]


ALL_LISTS = {
    "POOL_CHECKLIST_DEFAULT (routers/service_reports.py)": POOL_CHECKLIST_DEFAULT,
    "POOL_CHECKLIST (routers/jobs.py)":                    POOL_CHECKLIST,
    "DEFAULT_POOL_ITEMS (routers/checklists.py)":          DEFAULT_POOL_ITEMS,
    "CANONICAL_POOL_CHECKLIST (routers/document_generators.py)": CANONICAL_POOL_CHECKLIST,
}


# ─── (1) Membership across every canonical list ─────────────────────
@pytest.mark.parametrize("list_name,items", list(ALL_LISTS.items()))
@pytest.mark.parametrize("expected", NEW_ITEMS)
def test_new_item_present_in_every_default_list(list_name: str, items, expected: str) -> None:
    labels = _labels(items)
    assert expected in labels, (
        f"{expected!r} missing from {list_name}. Present labels: {labels!r}"
    )


# ─── (2) Exact casing / spacing (belt & braces) ─────────────────────
@pytest.mark.parametrize("list_name,items", list(ALL_LISTS.items()))
def test_new_items_use_exact_casing_and_spacing(list_name: str, items) -> None:
    """No sneaky case/whitespace drift — the product brief spelled these
    verbatim as ``Emptied skimmer basket`` / ``Emptied leaf canister`` /
    ``Emptied Betta Skimmer``. Reject any variant that only matches
    case-insensitively."""
    labels = _labels(items)
    lower_labels = [l.lower() for l in labels]
    for expected in NEW_ITEMS:
        # If the case-insensitive match exists, the exact-case match must too.
        if expected.lower() in lower_labels:
            assert expected in labels, (
                f"{expected!r} exists in {list_name} but with wrong casing/spacing. "
                f"Present labels: {labels!r}"
            )


# ─── (3) Contiguous trailing block (order guarantee) ────────────────
@pytest.mark.parametrize("list_name,items", list(ALL_LISTS.items()))
def test_new_items_are_a_contiguous_trailing_block(list_name: str, items) -> None:
    labels = _labels(items)
    assert labels[-3:] == NEW_ITEMS, (
        f"{list_name}: expected the last three entries to be {NEW_ITEMS!r} "
        f"in order, got {labels[-3:]!r} (full list: {labels!r})"
    )


# ─── (4) Items are OPTIONAL — no required/mandatory flag ────────────
@pytest.mark.parametrize("list_name,items", list(ALL_LISTS.items()))
def test_new_items_are_not_marked_required(list_name: str, items) -> None:
    for item in items:
        label = _label(item)
        if label not in NEW_ITEMS:
            continue
        if isinstance(item, dict):
            for flag in ("required", "mandatory", "is_required"):
                assert not item.get(flag), (
                    f"{list_name}: {label!r} must remain optional but has "
                    f"{flag}={item.get(flag)!r}"
                )
        # str items have no metadata — trivially optional.


# ─── (5) Chemistry gate must NOT gate on any of these ───────────────
def test_new_items_do_not_appear_in_chemistry_gate() -> None:
    """The three optional items must never be promoted into the
    chemistry-gate required-readings surface. If a future refactor
    reshapes the gate, this test will loudly regress before shipping."""
    from services import chemistry_gate

    # Pull every string-like constant defined at module level so we
    # catch CORE_READINGS, REQUIRED_READINGS, _ALIASES, and any future
    # rename without hard-coding names that may drift.
    haystacks: List[str] = []
    for attr in dir(chemistry_gate):
        if attr.startswith("__"):
            continue
        try:
            val = getattr(chemistry_gate, attr)
        except Exception:
            continue
        if isinstance(val, str):
            haystacks.append(val)
        elif isinstance(val, (list, tuple, set, frozenset)):
            haystacks.extend(str(x) for x in val)
        elif isinstance(val, dict):
            haystacks.extend(str(k) for k in val.keys())
            haystacks.extend(str(v) for v in val.values())

    joined = "\n".join(haystacks).lower()
    for expected in NEW_ITEMS:
        assert expected.lower() not in joined, (
            f"{expected!r} leaked into chemistry_gate — it must remain a "
            f"non-blocking checklist item, not a gated reading."
        )


# ─── (6) No duplicate labels introduced by the append ───────────────
@pytest.mark.parametrize("list_name,items", list(ALL_LISTS.items()))
def test_no_duplicate_labels_after_append(list_name: str, items) -> None:
    labels = _labels(items)
    dupes = sorted({l for l in labels if labels.count(l) > 1})
    assert not dupes, f"{list_name}: duplicate checklist labels: {dupes!r}"
