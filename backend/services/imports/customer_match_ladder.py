"""Feb-2026 · PDF-import customer-match ladder.

Companion to :mod:`services.imports.customer_autocreate`.  Prior to
this ladder, the commit-time dedupe at
``customer_autocreate._find_existing_customer`` only matched on
exact normalized name/address/phone against the tenant's
not-soft-deleted customer pool, and the preview-time match at
``pdf_mapper._fuzzy_match_customer`` filtered the pool to
``is_active != False``.  Operators reported duplicate customer
rows getting minted when the extracted name matched an INACTIVE
or MUTED customer with a slight extraction variance (missing
address, name typo, ``&`` vs ``and``, etc.).

This module adds a strict ordered ladder consulted BEFORE the
``_insert_auto_customer`` fallback fires:

  1. Exact normalized name match on ACTIVE customers
  2. Exact normalized name match on INACTIVE customers
  3. Exact normalized name match on MUTED customers
  4. Fuzzy name match across ALL statuses — Levenshtein distance
     ≤ ``_FUZZY_MAX_DIST`` (default 2) OR normalized substring
     match.  Ambiguity (2+ candidates at the minimum distance)
     DEMOTES to ``requires_manual_resolution`` so the operator
     resolves via the inline picker; the ladder NEVER silently
     attaches to the wrong customer.
  5. Only if 1-4 all miss, auto-create (handled by the caller).

Status taxonomy (mirrors ``routers/dashboard.py::active_customers_count``
and ``routers/dashboard.py::inactive_customers_count``):

  * ``active``   — ``is_active != False`` (True / missing / null)
                   AND not soft-deleted.
  * ``inactive`` — ``is_active == False`` AND ``is_muted != True``
                   AND not soft-deleted.
  * ``muted``    — ``is_muted == True`` AND not soft-deleted.
                   Muted supersedes inactive — a row with both
                   ``is_active=False`` AND ``is_muted=True`` is
                   classified ``muted`` by the ladder so the UI
                   surfaces the stronger signal.

Normalization:

  * ``_norm_text`` from :mod:`customer_autocreate` — lowercase +
    whitespace collapse (shared contract).
  * Additionally in this module: ``&`` ↔ ``and`` normalization +
    punctuation strip for the fuzzy-tier canonical form.  Keeps
    ``"Joe & Jane Smith"`` and ``"Joe and Jane Smith"`` exact-tier
    equivalent, not fuzzy.

No new 3rd-party dep — Levenshtein implemented inline with
early-exit at ``max_dist + 1`` for the hot path.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.imports.customer_autocreate import _norm_text, _norm_phone


logger = logging.getLogger("imports.customer_match_ladder")


# Default Levenshtein ceiling.  Dispatch spec: "distance ≤ 2".
_FUZZY_MAX_DIST = 2

# Minimum extracted-name length before we're willing to run the
# fuzzy tier.  Three characters is too short to be meaningful at
# a 2-edit distance (every 3-char name is within 2 edits of every
# other 3-char name).  Keeps the ladder from producing noise
# matches on initials ("A B") or empty-string artefacts.
_FUZZY_MIN_NAME_LEN = 5


# ═════════════════════════════════════════════════════════════
# Public types
# ═════════════════════════════════════════════════════════════
@dataclass
class LadderCandidate:
    """One customer surfaced as a potential fuzzy match."""
    customer_id: str
    customer_name: str
    customer_status: str   # "active" | "inactive" | "muted"
    fuzzy_distance: int


@dataclass
class LadderResult:
    """Outcome of running the ladder for a single pending row.

    ``match_status`` values::

      * ``"active"``    — exact match tier 1.
      * ``"inactive"``  — exact match tier 2.
      * ``"muted"``     — exact match tier 3.
      * ``"fuzzy_match"`` — unique fuzzy match tier 4.
      * ``"requires_manual_resolution"`` — tier 4 found 2+
        candidates at the minimum distance.  Caller surfaces
        ``candidates`` so the operator picks one.
      * ``"will_auto_create"`` — tiers 1-4 all missed.

    ``match_method`` is ``"exact"`` for tiers 1-3, ``"fuzzy"``
    for tier 4, and ``None`` for ``"will_auto_create"`` /
    ``"requires_manual_resolution"``.

    ``match_confidence`` is ``1.0`` for exact, lower for fuzzy
    (``1.0 - distance / (max_dist + 1)``).  ``None`` for no-match.

    ``fuzzy_distance`` is only populated when ``match_method ==
    "fuzzy"`` (or when ``candidates`` is non-empty).
    """
    match_status: str
    matched_customer_id: Optional[str] = None
    matched_customer_name: Optional[str] = None
    matched_customer_status: Optional[str] = None
    match_method: Optional[str] = None
    match_confidence: Optional[float] = None
    fuzzy_distance: Optional[int] = None
    candidates: List[LadderCandidate] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════
# Normalization helpers (ladder-local extension)
# ═════════════════════════════════════════════════════════════
_PUNCT_RE = re.compile(r"[^a-z0-9&\s]+")
_AMPERSAND_RE = re.compile(r"\s*&\s*")
_AND_WORD_RE = re.compile(r"\b and \b")
_WS_RE = re.compile(r"\s+")


def _canon_name(s: Optional[str]) -> str:
    """Canonical-form normalization used by BOTH the exact and
    fuzzy tiers so ``"Joe & Jane Smith"`` and
    ``"Joe and Jane Smith"`` match at the exact tier (not fuzzy).

    Lowercase → strip non-alphanumeric except ``&`` and whitespace
    → canonicalize ``&`` ↔ ``and`` → collapse whitespace.
    """
    if not s:
        return ""
    v = str(s).lower().strip()
    v = _PUNCT_RE.sub(" ", v)
    v = _AMPERSAND_RE.sub(" and ", v)
    # Belt-and-braces: ``"foo  and  bar"`` → ``"foo and bar"``.
    v = _WS_RE.sub(" ", v).strip()
    return v


# ═════════════════════════════════════════════════════════════
# Levenshtein — inline, early-exit
# ═════════════════════════════════════════════════════════════
def levenshtein(a: str, b: str, max_dist: int) -> int:
    """Classic Levenshtein with early-exit at ``max_dist + 1``.

    Returns the actual distance when it is ``<= max_dist``, else
    returns ``max_dist + 1`` as a sentinel (caller treats any
    value ``> max_dist`` as "no match").  Keeps the hot path
    bounded even for pathological inputs — a 50-char name vs a
    1-char candidate exits after ``max_dist + 1`` iterations
    on the length-delta short-circuit alone.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    if la == 0:
        return lb if lb <= max_dist else max_dist + 1
    if lb == 0:
        return la if la <= max_dist else max_dist + 1
    # Two-row DP with early-exit — the whole row must have at
    # least one cell <= max_dist, else no path through completes
    # under the ceiling.
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        row_min = curr[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,       # deletion
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost,  # substitution
            )
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > max_dist:
            return max_dist + 1
        prev = curr
    return prev[lb] if prev[lb] <= max_dist else max_dist + 1


# ═════════════════════════════════════════════════════════════
# Row-status classifier (mirrors dashboard.py)
# ═════════════════════════════════════════════════════════════
def _classify_row_status(row: Dict[str, Any]) -> str:
    """Return ``"active" | "inactive" | "muted"`` for one
    customer row.  Caller filters out soft-deleted rows before
    this helper is reached.

    Muted supersedes inactive — if ``is_muted == True``, the
    row is classified ``"muted"`` regardless of ``is_active``.
    """
    if row.get("is_muted") is True:
        return "muted"
    if row.get("is_active") is False:
        return "inactive"
    return "active"


# ═════════════════════════════════════════════════════════════
# Ladder entry point
# ═════════════════════════════════════════════════════════════
async def run_match_ladder(
    *,
    db,
    tenant_id: str,
    extracted_name: str,
    extracted_address: Optional[str] = None,
    extracted_phone: Optional[str] = None,
    max_fuzzy_distance: int = _FUZZY_MAX_DIST,
) -> LadderResult:
    """Run the full match ladder against the tenant's customer
    pool.  Caller is responsible for the ``PENDING::`` /
    low-confidence gating already in place in
    :mod:`customer_autocreate` — this helper assumes the row
    carries at least one usable signal.

    Scans ``db.customers`` tenant-scoped ONCE and partitions
    rows by status in-memory — keeps the ladder to a single DB
    round-trip even on cold batches.

    Soft-deleted customers are excluded (``deleted_at`` sentinel
    shape from Phase 33 Step B).

    Tier precedence: active-exact → inactive-exact → muted-exact
    → fuzzy-across-all-statuses.
    """
    norm_name_canon = _canon_name(extracted_name)
    norm_phone_digits = _norm_phone(extracted_phone)

    # Zero-signal rows should have been filtered by the caller;
    # defensively return will_auto_create so a programmer error
    # upstream doesn't silently become a duplicate.
    if not norm_name_canon and not norm_phone_digits:
        return LadderResult(match_status="will_auto_create")

    projection = {
        "_id": 0, "id": 1, "name": 1, "phone": 1,
        "is_active": 1, "is_muted": 1,
    }
    # Soft-delete sentinel matches the Phase 33 Step B shape at
    # ``customer_autocreate._find_existing_customer`` so the
    # ladder sees the same pool.  Use ``async for`` iteration
    # (not ``cursor.to_list``) so the same test mocks the
    # legacy ``_find_existing_customer`` suite ships work for
    # the ladder too.
    cursor = db.customers.find(
        {
            "tenant_id": tenant_id,
            "deleted_at": {"$in": [None, "", False]},
            # Feb-2026 · TD-pdf-import-operator-confirm-before-create
            # Part 2 — exclude merged ("ghost") customers from the
            # match pool.  Without this filter the ladder picked
            # ghost records (``merged_into`` set) and new imports
            # re-attached invoices to the loser side of a prior
            # merge (surfaced live preview as orphan invoice
            # 3d358d7f… against merged customer d4405b9c…;
            # repaired by TD-invoice-customer-id-repair-on-merge).
            # Filter shape mirrors ``routers/customers.py`` line
            # 1490 so the ladder's pool matches the admin
            # customer list's default-visible pool.
            "$or": [
                {"merged_into": None},
                {"merged_into": {"$exists": False}},
            ],
        },
        projection,
    )
    rows: List[Dict[str, Any]] = []
    async for row in cursor:
        rows.append(row)
    if not rows:
        return LadderResult(match_status="will_auto_create")

    # Partition by status in a single pass.
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "active": [], "inactive": [], "muted": [],
    }
    for r in rows:
        buckets[_classify_row_status(r)].append(r)

    # ── Tiers 1-3: exact normalized name match per status ──
    if norm_name_canon:
        for status in ("active", "inactive", "muted"):
            for r in buckets[status]:
                if _canon_name(r.get("name")) == norm_name_canon:
                    return LadderResult(
                        match_status=status,
                        matched_customer_id=r["id"],
                        matched_customer_name=r.get("name") or "",
                        matched_customer_status=status,
                        match_method="exact",
                        match_confidence=1.0,
                    )

    # ── Tier 4: fuzzy match across all statuses ──
    # Guard against noise-matches on very short extracted names.
    if (
        norm_name_canon
        and len(norm_name_canon) >= _FUZZY_MIN_NAME_LEN
    ):
        best_dist = max_fuzzy_distance + 1
        hits: List[LadderCandidate] = []
        for status in ("active", "inactive", "muted"):
            for r in buckets[status]:
                row_canon = _canon_name(r.get("name"))
                if not row_canon:
                    continue
                # Substring match counts as distance 0 for the
                # ladder's purposes (operator confirmed the two
                # names are semantically the same — e.g.
                # "Joe Kail" extracted vs "Joe Kail Pool Service"
                # in DB).  Only kicks in when the shorter form
                # is at least _FUZZY_MIN_NAME_LEN long so we
                # don't substring-match initials.
                if (
                    len(row_canon) >= _FUZZY_MIN_NAME_LEN
                    and (
                        norm_name_canon in row_canon
                        or row_canon in norm_name_canon
                    )
                ):
                    cand = LadderCandidate(
                        customer_id=r["id"],
                        customer_name=r.get("name") or "",
                        customer_status=status,
                        fuzzy_distance=0,
                    )
                    if 0 < best_dist:
                        best_dist = 0
                        hits = [cand]
                    elif 0 == best_dist:
                        hits.append(cand)
                    continue
                d = levenshtein(
                    norm_name_canon, row_canon, max_fuzzy_distance,
                )
                if d > max_fuzzy_distance:
                    continue
                if d < best_dist:
                    best_dist = d
                    hits = [LadderCandidate(
                        customer_id=r["id"],
                        customer_name=r.get("name") or "",
                        customer_status=status,
                        fuzzy_distance=d,
                    )]
                elif d == best_dist:
                    hits.append(LadderCandidate(
                        customer_id=r["id"],
                        customer_name=r.get("name") or "",
                        customer_status=status,
                        fuzzy_distance=d,
                    ))

        if len(hits) == 1:
            h = hits[0]
            # Confidence scales with distance — 1.0 at exact
            # (shouldn't happen on this branch, caught by
            # tiers 1-3) down to a positive floor at the
            # ceiling.
            confidence = max(
                0.0,
                1.0 - (h.fuzzy_distance / (max_fuzzy_distance + 1)),
            )
            return LadderResult(
                match_status="fuzzy_match",
                matched_customer_id=h.customer_id,
                matched_customer_name=h.customer_name,
                matched_customer_status=h.customer_status,
                match_method="fuzzy",
                match_confidence=round(confidence, 2),
                fuzzy_distance=h.fuzzy_distance,
                candidates=[h],
            )
        if len(hits) >= 2:
            # Ambiguity → operator picks via inline picker.
            return LadderResult(
                match_status="requires_manual_resolution",
                match_method="fuzzy",
                fuzzy_distance=best_dist,
                candidates=hits,
            )

    # Tiers 1-4 all missed → caller will mint a fresh customer.
    return LadderResult(match_status="will_auto_create")


__all__ = [
    "LadderCandidate",
    "LadderResult",
    "levenshtein",
    "run_match_ladder",
    "_canon_name",
    "_classify_row_status",
    "_FUZZY_MAX_DIST",
    "_FUZZY_MIN_NAME_LEN",
]
