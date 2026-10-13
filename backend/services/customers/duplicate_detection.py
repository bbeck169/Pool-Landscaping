"""Feb-2026 · duplicate-customer detection service.

Backs the Duplicates tab on the Customers list page and the
``GET /api/customers/duplicates`` endpoint.

Match criteria (any one hit groups customers together):

  * ``name_exact``  — ``_canon_name`` from
    :mod:`services.imports.customer_match_ladder` (lowercase +
    whitespace collapse + ``&↔and`` + punctuation strip).  Same
    canonical form as the PDF-import ladder's tiers 1-3 so the
    two surfaces never disagree on "same name".
  * ``phone``       — ``_norm_phone`` from
    :mod:`services.imports.customer_autocreate` (digits-only).
    Country-code 1 retained (defensive — two numbers that differ
    by a country code might be different customers).
  * ``email``       — lowercase + strip.
  * ``name_fuzzy``  — Levenshtein ``<= 2`` on the canonical names
    OR normalized substring (both sides ≥ 5 chars).  Reuses
    :func:`services.imports.customer_match_ladder.levenshtein`
    for behavioural consistency with the PDF-import ladder.

Design notes:

  * Tenant-scoped.  Excludes soft-deleted via the shared sentinel
    shape ``deleted_at: {$in: [None, "", False]}``.
  * Includes active + inactive + muted customers (the Duplicates
    tab shows ALL statuses so operators can clean up legacy
    duplicates regardless of lifecycle flag).
  * Union-find style grouping: build a disjoint-set over
    customer ids as each predicate is evaluated, so a customer
    linked to A by phone and to B by name lands in a single
    group ``{A, B, self}``.
  * Perf: exact-tier predicates are O(N) with a hash-key sweep.
    The fuzzy tier is O(N^2) over customers with canonical names
    ≥ 5 chars — bounded to tenants with <10K customers.  Above
    that threshold the fuzzy sweep is SKIPPED (not slow-path'd)
    and a WARN is logged with ``kind=perf.fuzzy_skipped
    tenant_id=... customer_count=...``; exact tiers still run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from services.imports.customer_autocreate import _norm_phone
from services.imports.customer_match_ladder import (
    _canon_name,
    levenshtein,
)


logger = logging.getLogger("customers.duplicate_detection")


# Perf ceiling for the O(N^2) fuzzy sweep.  Above this count the
# fuzzy tier is skipped (not slow-path'd) and the WARN is emitted.
_FUZZY_SWEEP_CUSTOMER_CEILING = 10_000

# Minimum canonical-name length for the fuzzy tier.  Mirrors the
# PDF-import ladder's ``_FUZZY_MIN_NAME_LEN`` so a 3-char name
# never produces noise matches.
_FUZZY_MIN_NAME_LEN = 5

# Levenshtein ceiling for the fuzzy tier.  Mirrors the ladder's
# default.
_FUZZY_MAX_DIST = 2

# Valid match-reason tokens.  Keep in alphabetical order so the
# FE's chip rendering is deterministic.
_MATCH_REASONS = ("email", "name_exact", "name_fuzzy", "phone")


# ═════════════════════════════════════════════════════════════
# Public dataclasses
# ═════════════════════════════════════════════════════════════
@dataclass
class CustomerSummary:
    """Thin customer summary surfaced in the duplicate group.
    Carries only the fields the Duplicates tab renders — the
    full customer doc stays in ``db.customers``.
    """
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    status: str = "active"     # "active" | "inactive" | "muted"
    created_at: Optional[str] = None


@dataclass
class DuplicateGroup:
    group_id: str
    match_reasons: List[str] = field(default_factory=list)
    customers: List[CustomerSummary] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════
# Union-find over customer ids
# ═════════════════════════════════════════════════════════════
class _UnionFind:
    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x

    def find(self, x: str) -> str:
        # Path compression — O(α(N)) amortised.
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        self.add(a); self.add(b)
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for x in list(self._parent):
            r = self.find(x)
            out.setdefault(r, []).append(x)
        return out


# ═════════════════════════════════════════════════════════════
# Classifier (mirrors the ladder)
# ═════════════════════════════════════════════════════════════
def _status_of(row: Dict[str, Any]) -> str:
    """Return ``active`` | ``inactive`` | ``muted`` — muted
    supersedes inactive, matching the PDF-import ladder's
    taxonomy at :mod:`services.imports.customer_match_ladder`.
    """
    if row.get("is_muted") is True:
        return "muted"
    if row.get("is_active") is False:
        return "inactive"
    return "active"


# ═════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════
async def detect_duplicates(
    *,
    db,
    tenant_id: str,
    status_scope: Optional[List[str]] = None,
) -> List[DuplicateGroup]:
    """Scan the tenant's not-soft-deleted customer pool and
    return every group of 2+ customers sharing at least one
    match predicate.

    ``status_scope`` is an optional filter: if provided, only
    customers whose derived status is in the scope are
    considered as grouping candidates.  Defaults to all three
    (``["active", "inactive", "muted"]``) — the tab shows every
    duplicate regardless of lifecycle flag.
    """
    scope = set(status_scope) if status_scope else {
        "active", "inactive", "muted",
    }

    projection = {
        "_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
        "is_active": 1, "is_muted": 1, "created_at": 1,
    }
    cursor = db.customers.find(
        {"tenant_id": tenant_id,
          "deleted_at": {"$in": [None, "", False]}},
        projection,
    )
    rows: List[Dict[str, Any]] = []
    async for r in cursor:
        rows.append(r)

    # Build the fast-lookup structures in one pass.
    by_id: Dict[str, Dict[str, Any]] = {}
    canon_names: Dict[str, str] = {}      # cid -> canonical name
    phone_digits: Dict[str, str] = {}     # cid -> digits
    email_norm: Dict[str, str] = {}       # cid -> lowercased email
    row_status: Dict[str, str] = {}       # cid -> status
    for r in rows:
        cid = r.get("id")
        if not cid:
            continue
        row_status[cid] = _status_of(r)
        if row_status[cid] not in scope:
            # Filter to the operator's scope — a row outside
            # the scope cannot anchor a group AND cannot be
            # grouped with another candidate.
            continue
        by_id[cid] = r
        canon_names[cid] = _canon_name(r.get("name"))
        phone_digits[cid] = _norm_phone(r.get("phone"))
        em = r.get("email")
        email_norm[cid] = (em or "").strip().lower()

    if len(by_id) < 2:
        return []

    uf = _UnionFind()
    for cid in by_id:
        uf.add(cid)

    # Per-pair match-reason tracking — a pair that linked via
    # BOTH name_exact AND phone surfaces both reasons on the
    # resulting group.
    group_reasons: Dict[Tuple[str, str], set] = {}

    def _pair_key(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def _link(a: str, b: str, reason: str) -> None:
        if a == b:
            return
        key = _pair_key(a, b)
        group_reasons.setdefault(key, set()).add(reason)
        uf.union(a, b)

    # ── Tier 1 · exact normalized name ──
    name_bucket: Dict[str, List[str]] = {}
    for cid, n in canon_names.items():
        if not n:
            continue
        name_bucket.setdefault(n, []).append(cid)
    for bucket in name_bucket.values():
        if len(bucket) < 2:
            continue
        anchor = bucket[0]
        for other in bucket[1:]:
            _link(anchor, other, "name_exact")

    # ── Tier 2 · exact phone (digits-only) ──
    phone_bucket: Dict[str, List[str]] = {}
    for cid, p in phone_digits.items():
        if not p:
            continue
        phone_bucket.setdefault(p, []).append(cid)
    for bucket in phone_bucket.values():
        if len(bucket) < 2:
            continue
        anchor = bucket[0]
        for other in bucket[1:]:
            _link(anchor, other, "phone")

    # ── Tier 3 · exact email (lowercased + stripped) ──
    email_bucket: Dict[str, List[str]] = {}
    for cid, e in email_norm.items():
        if not e:
            continue
        email_bucket.setdefault(e, []).append(cid)
    for bucket in email_bucket.values():
        if len(bucket) < 2:
            continue
        anchor = bucket[0]
        for other in bucket[1:]:
            _link(anchor, other, "email")

    # ── Tier 4 · fuzzy name (Levenshtein ≤ 2 OR substring) ──
    # O(N^2) over fuzzy-eligible rows.  Bounded by the ceiling —
    # above that we skip + WARN rather than hang the request.
    fuzzy_candidates = [
        (cid, canon_names[cid]) for cid in by_id
        if len(canon_names.get(cid, "") or "") >= _FUZZY_MIN_NAME_LEN
    ]
    if len(fuzzy_candidates) > _FUZZY_SWEEP_CUSTOMER_CEILING:
        logger.warning(
            "[duplicate_detection] kind=perf.fuzzy_skipped "
            "tenant_id=%s customer_count=%d ceiling=%d — "
            "exact tiers still ran.",
            tenant_id, len(fuzzy_candidates),
            _FUZZY_SWEEP_CUSTOMER_CEILING,
        )
    else:
        n = len(fuzzy_candidates)
        for i in range(n):
            cid_a, n_a = fuzzy_candidates[i]
            for j in range(i + 1, n):
                cid_b, n_b = fuzzy_candidates[j]
                # Already linked under an exact tier?  Still
                # record ``name_fuzzy`` as a reason only if the
                # fuzzy predicate ALSO hits — the FE renders
                # the full reason list for the pair.
                if (n_a == n_b):
                    # Exact-name hit — tier 1 already linked
                    # them AND stamped ``name_exact``.  Skip
                    # to avoid misreporting as fuzzy.
                    continue
                is_substr = (
                    len(n_b) >= _FUZZY_MIN_NAME_LEN
                    and len(n_a) >= _FUZZY_MIN_NAME_LEN
                    and (n_a in n_b or n_b in n_a)
                )
                d = (
                    0 if is_substr
                    else levenshtein(n_a, n_b, _FUZZY_MAX_DIST)
                )
                if d <= _FUZZY_MAX_DIST:
                    _link(cid_a, cid_b, "name_fuzzy")

    # ── Materialise groups ──
    # The union-find's groups() contains every added id — groups
    # of size 1 are singletons we filter out.
    out_groups: List[DuplicateGroup] = []
    for root, members in uf.groups().items():
        if len(members) < 2:
            continue
        # Collect reasons across every pair in the group.
        reasons: set = set()
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                key = _pair_key(members[i], members[j])
                reasons |= group_reasons.get(key, set())
        if not reasons:
            # Defensive — a group with no reasons shouldn't
            # exist (union-find only links on a reason), but
            # if the invariant ever breaks we skip rather
            # than surface a mystery group.
            continue
        # Deterministic customer order: by created_at then id so
        # the FE renders the oldest customer in the leftmost
        # column (operators usually keep the oldest).
        #
        # Legacy ``created_at`` can be either a native datetime
        # (newer rows written through pydantic models) or an ISO
        # string (older rows persisted raw).  Coerce to a
        # string key before sort so the comparison never raises
        # ``TypeError: '<' not supported between datetime and str``.
        def _ts_key(r: Dict[str, Any]) -> Tuple[str, str]:
            ca = r.get("created_at")
            if ca is None:
                ca_str = ""
            elif hasattr(ca, "isoformat"):
                ca_str = ca.isoformat()
            else:
                ca_str = str(ca)
            return (ca_str, r.get("id") or "")
        member_rows = sorted(
            [by_id[m] for m in members if m in by_id],
            key=_ts_key,
        )
        group = DuplicateGroup(
            group_id=root,
            match_reasons=sorted(
                r for r in reasons if r in _MATCH_REASONS
            ),
            customers=[
                CustomerSummary(
                    id=r["id"],
                    name=r.get("name") or "",
                    email=r.get("email") or None,
                    phone=r.get("phone") or None,
                    status=row_status.get(r["id"], "active"),
                    created_at=r.get("created_at"),
                )
                for r in member_rows
            ],
        )
        out_groups.append(group)

    # Group ordering: largest group first, then by group_id for
    # stability.  Keeps the "worst offender" at the top of the
    # Duplicates tab.
    out_groups.sort(
        key=lambda g: (-len(g.customers), g.group_id),
    )
    return out_groups


__all__ = [
    "CustomerSummary",
    "DuplicateGroup",
    "detect_duplicates",
    "_FUZZY_SWEEP_CUSTOMER_CEILING",
    "_FUZZY_MIN_NAME_LEN",
    "_FUZZY_MAX_DIST",
]
