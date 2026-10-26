"""Feb 2026 · Customer Merge · Phase 1 — duplicate detection engine.

Four match strategies (any-of-four → duplicate candidate):

  1. Exact email match (case-insensitive, whitespace trimmed).
  2. Exact phone match (normalized to digits-only for comparison).
  3. Exact name + address match (case-insensitive, whitespace collapsed).
  4. Fuzzy name (Jaro-Winkler ≥ 0.92 default threshold).

Confidence tier (per user decision):
  * ``high`` — exact email OR exact phone. Auto-mergeable in Phase 3.
  * ``low``  — exact name+address OR fuzzy name. Requires admin review.

All output is tenant-scoped. Already-merged (``merged_into`` set) and
soft-deleted (``deleted_at`` set) rows are excluded from every match
strategy so an admin never sees a stale duplicate group.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from config import db


# ─── Jaro-Winkler (in-process, no dep) ──────────────────────────────
def _jaro_similarity(s1: str, s2: str) -> float:
    """Return the Jaro similarity between two strings in [0.0, 1.0].

    Reference: Winkler 1990.  Same-length + identical strings score
    1.0; disjoint character sets score 0.0.
    """
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if l1 == 0 or l2 == 0:
        return 0.0
    match_dist = max(l1, l2) // 2 - 1
    if match_dist < 0:
        match_dist = 0
    s1_matches = [False] * l1
    s2_matches = [False] * l2
    matches = 0
    transpositions = 0
    for i in range(l1):
        start = max(0, i - match_dist)
        end = min(i + match_dist + 1, l2)
        for j in range(start, end):
            if s2_matches[j]:
                continue
            if s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    k = 0
    for i in range(l1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    transpositions //= 2
    return (
        matches / l1
        + matches / l2
        + (matches - transpositions) / matches
    ) / 3.0


def jaro_winkler(s1: str, s2: str, prefix_scale: float = 0.1) -> float:
    """Jaro-Winkler variant that boosts scores for common prefixes.

    ``prefix_scale`` defaults to 0.1 per Winkler's original paper;
    max common prefix considered is 4 chars.
    """
    if not s1 or not s2:
        return 0.0
    j = _jaro_similarity(s1, s2)
    if j < 0.7:  # only boost strong matches (Winkler's own guidance)
        return j
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a == b:
            prefix += 1
        else:
            break
    return j + prefix * prefix_scale * (1.0 - j)


# ─── Normalisers ────────────────────────────────────────────────────
_PHONE_DIGITS = re.compile(r"\D+")


def _norm_email(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    t = str(v).strip().lower()
    return t or None


def _norm_phone(v: Optional[str]) -> Optional[str]:
    """Digits-only normalisation with US ``1`` country-code strip so
    ``+1 (623) 555-0100`` and ``623-555-0100`` compare equal. Numbers
    shorter than 7 digits are treated as junk (return None). The
    ``1`` collapse is US-only per the current tenant profile; if we
    expand internationally, promote this to a country-aware library
    (libphonenumber)."""
    if not v:
        return None
    digits = _PHONE_DIGITS.sub("", str(v))
    if len(digits) < 7:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _norm_name(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    t = re.sub(r"\s+", " ", str(v).strip().lower())
    return t or None


def _norm_address(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    t = re.sub(r"\s+", " ", str(v).strip().lower())
    return t or None


# ─── Public API ─────────────────────────────────────────────────────
def _base_filter(tenant_id: str) -> Dict[str, Any]:
    """Common exclusion filter: current tenant, not merged, not soft
    deleted. Every strategy layers this in before running."""
    return {
        "tenant_id": tenant_id,
        "$and": [
            {"$or": [{"merged_into": None},
                       {"merged_into": {"$exists": False}}]},
            {"$or": [{"deleted_at": None},
                       {"deleted_at": {"$exists": False}}]},
        ],
    }


async def _load_active_customers(tenant_id: str) -> List[Dict[str, Any]]:
    """Load every active (non-merged, non-deleted) customer for the
    tenant. Kept as a single fetch so downstream strategies can share
    it — avoids 4x the same collection scan."""
    cur = db.customers.find(
        _base_filter(tenant_id),
        {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1,
         "email": 1, "phone": 1, "address": 1,
         "address_line1": 1, "city": 1, "state": 1, "postal_code": 1,
         "updated_at": 1, "created_at": 1},
    )
    return await cur.to_list(20000)


def _address_of(row: Dict[str, Any]) -> Optional[str]:
    """Compose a stable address string from either the free-form
    ``address`` scalar OR the structured fields introduced in P41."""
    a = _norm_address(row.get("address"))
    if a:
        return a
    parts = [
        _norm_address(row.get("address_line1")),
        _norm_address(row.get("city")),
        _norm_address(row.get("state")),
        _norm_address(row.get("postal_code")),
    ]
    joined = " ".join(p for p in parts if p)
    return joined or None


def _bucket_by(rows: List[Dict[str, Any]],
                key_fn) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        k = key_fn(r)
        if not k:
            continue
        out.setdefault(k, []).append(r)
    # Only keep buckets with ≥2 members (that's what "duplicate" means).
    return {k: v for k, v in out.items() if len(v) >= 2}


def _group_from_bucket(
    match_type: str,
    confidence: str,
    field_values: Dict[str, Any],
    members: List[Dict[str, Any]],
    score: float = 1.0,
) -> Dict[str, Any]:
    return {
        "match_type": match_type,
        "confidence": confidence,
        "score": score,
        "customer_ids": [m["id"] for m in members],
        "match_field_values": field_values,
    }


async def detect_duplicates_for_tenant(
    tenant_id: str,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return a list of duplicate groups for the tenant.

    Group shape::

        {
          "match_type": "exact_email"|"exact_phone"|
                          "exact_name_address"|"fuzzy_name",
          "confidence": "high" | "low",
          "score": <float>,  # Jaro-Winkler for fuzzy, 1.0 exact
          "customer_ids": ["<id1>", "<id2>", ...],
          "match_field_values": { <keys per match_type> }
        }

    ``filters`` (optional): forward-compat surface. Currently supports:
      * ``min_score`` (float, default 0.92) — fuzzy name threshold.
      * ``exclude_match_types`` (list[str]) — skip specific strategies.
      * ``customer_ids`` (list[str]) — restrict output to groups whose
        member set is a **subset** of the given ids. Used by the
        Phase-2 merge modal so its detection banner only surfaces
        matches involving the currently-checked customers.
    """
    filters = filters or {}
    min_score = float(filters.get("min_score") or 0.92)
    exclude = set(filters.get("exclude_match_types") or [])
    scope_ids = filters.get("customer_ids") or []
    if scope_ids and not isinstance(scope_ids, (list, tuple, set)):
        scope_ids = [scope_ids]
    scope_set = set(scope_ids) if scope_ids else None
    if not tenant_id:
        return []
    rows = await _load_active_customers(tenant_id)
    if not rows:
        return []
    # Scope filter — only when the caller passed a customer_ids
    # subset. Any group whose member set escapes this subset is
    # dropped so the Phase-2 merge modal's detection banner reflects
    # ONLY matches involving currently-checked rows.
    if scope_set is not None:
        rows = [r for r in rows if r.get("id") in scope_set]
        if not rows:
            return []

    # The matching below is CPU-bound (the fuzzy tier is an all-pairs
    # Jaro-Winkler sweep).  Run it on a worker thread so it cannot
    # stall the event loop and every other request along with it.
    return await asyncio.to_thread(
        _detect_groups, rows, exclude, min_score,
    )


def _detect_groups(
    rows: List[Dict[str, Any]],
    exclude: set,
    min_score: float,
) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []

    # 1. Exact email
    if "exact_email" not in exclude:
        for key, members in _bucket_by(
            rows, lambda r: _norm_email(r.get("email"))
        ).items():
            groups.append(_group_from_bucket(
                "exact_email", "high",
                {"email": key}, members,
            ))

    # 2. Exact phone
    if "exact_phone" not in exclude:
        for key, members in _bucket_by(
            rows, lambda r: _norm_phone(r.get("phone"))
        ).items():
            groups.append(_group_from_bucket(
                "exact_phone", "high",
                {"phone": key}, members,
            ))

    # 3. Exact name + address
    if "exact_name_address" not in exclude:
        def _key(r):
            n = _norm_name(r.get("name"))
            a = _address_of(r)
            return f"{n}|{a}" if (n and a) else None
        for key, members in _bucket_by(rows, _key).items():
            n, a = key.split("|", 1)
            groups.append(_group_from_bucket(
                "exact_name_address", "low",
                {"name": n, "address": a}, members,
            ))

    # 4. Fuzzy name (Jaro-Winkler ≥ threshold, pairwise)
    if "fuzzy_name" not in exclude:
        already_grouped: set[frozenset[str]] = set()
        # De-dupe: never emit fuzzy groups that are already exact-email
        # or exact-phone matches (avoids noise in the review queue).
        for g in groups:
            already_grouped.add(frozenset(g["customer_ids"]))
        named = [(r, _norm_name(r.get("name"))) for r in rows]
        named = [(r, n) for r, n in named if n]
        seen: set[str] = set()
        for i, (a, an) in enumerate(named):
            if a["id"] in seen:
                continue
            cluster: List[Dict[str, Any]] = [a]
            best_score = 1.0
            for j in range(i + 1, len(named)):
                b, bn = named[j]
                # skip if already exact-matched pair
                if b["id"] in seen:
                    continue
                # exact name equality is handled by name+address; only
                # emit fuzzy for STRICTLY NON-EQUAL name strings
                if an == bn:
                    continue
                score = jaro_winkler(an, bn)
                if score >= min_score:
                    cluster.append(b)
                    best_score = min(best_score, score)
            if len(cluster) >= 2:
                key = frozenset(m["id"] for m in cluster)
                if key in already_grouped:
                    continue
                for m in cluster:
                    seen.add(m["id"])
                already_grouped.add(key)
                groups.append(_group_from_bucket(
                    "fuzzy_name", "low",
                    {"names": [m.get("name") for m in cluster]},
                    cluster,
                    score=round(best_score, 4),
                ))

    return groups
