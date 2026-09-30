"""Feb-2026 · preview_duplicate_jobs.py — READ-ONLY prod dedup preview.

Purpose
-------
Identify potential duplicate jobs for a customer (or all customers)
and emit a CSV that a human reviews BEFORE any delete happens.

The script performs ONLY Mongo reads.  Zero writes.  Pair with
``delete_duplicate_jobs.py`` (same dir) — that second script is the
mutation half of the workflow and requires an explicit ``--confirm``
flag.

Duplicate groups identified per customer:
  * Group A · Recurring    — jobs sharing a ``recurring_template_id``
                             (the parent template's occurrences).
  * Group B · Exact-dupe   — same ``scheduled_date`` AND same
                             ``title`` (perfect duplicates).
  * Group C · Near-adjacent — same ``title`` AND ``scheduled_date``
                              within ±5 minutes of another job
                              (fuzzy clone, common when a re-schedule
                              action forks the row without deleting
                              the old one).

Precedence: A > B > C.  A job that lands in an A cluster does NOT
also appear in B or C.  A job that lands in B does not also appear
in C.  Group C surfaces ONLY the fuzzy-only clones.

Per group (≥ 2 rows), the KEEP row is the one with the earliest
``created_at`` — that's the "originally scheduled occurrence" the
Task-D spec asks for.  Every other row is marked
``action=CANDIDATE_DELETE`` and written to the CSV alongside its
KEEP peer, so the reviewer sees both sides of every proposal.

Safe usage
----------
  export MONGO_URL="mongodb+srv://…prod-cluster…"
  export DB_NAME="Pool_&_Landscaping_of_Vistancia"

  # All customers, scoped to a tenant, custom CSV out
  python -m scripts.preview_duplicate_jobs \\
    --tenant-id affdfbfa-88b9-4baa-ae45-2ef78531b6e4 \\
    --output ./tmp/prod_dedup_preview.csv

  # Single customer, all tenants
  python -m scripts.preview_duplicate_jobs \\
    --customer-name "Lorena Olivas"

  # Edge: no filter — scans EVERY customer in the DB.  Use with care
  # on large tenants; the CSV can grow past 100k rows.
  python -m scripts.preview_duplicate_jobs

After review, the operator prunes the CSV down to the rows they
actually want deleted and feeds it to ``delete_duplicate_jobs.py``.

CLI args (both flags AND env vars accepted; flag wins if both set):
  --customer-name / $DEDUP_CUSTOMER_NAME  (optional substring match)
  --tenant-id     / $DEDUP_TENANT_ID      (optional single-tenant)
  --output        / $DEDUP_OUTPUT_CSV     (default duplicate_jobs_preview.csv)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ═════════════════════════════════════════════════════════════════
# Duplicate detection — pure, no I/O
# ═════════════════════════════════════════════════════════════════
FUZZY_WINDOW_SECONDS = 5 * 60  # Group C · ±5 min


def _parse_dt(v: Any) -> Optional[datetime]:
    """Return a timezone-aware ``datetime`` for a stored
    ``scheduled_date`` / ``created_at`` value.  Handles the three
    shapes Mongo docs carry in this codebase:
      * bare ISO date ``"YYYY-MM-DD"`` (schedule columns),
      * full ISO datetime string,
      * native ``datetime`` object.
    Returns ``None`` for empty / malformed inputs."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            # ``datetime.fromisoformat`` accepts both bare dates
            # and full timestamps.  Add a UTC anchor if the parsed
            # value is naive so ``timedelta`` math stays sane
            # cross-DST.
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                s = f"{s}T00:00:00+00:00"
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    return None


def _select_keep_id(group: List[Dict[str, Any]]) -> str:
    """Pick the job that stays.  Rule: earliest ``created_at`` (the
    "originally scheduled" occurrence).  Ties break on
    ``scheduled_date`` (earlier first) then ``id`` alphabetically
    so tests + human reviewers get deterministic output."""
    def _key(j):
        cdt = _parse_dt(j.get("created_at")) or datetime.max.replace(tzinfo=timezone.utc)
        sdt = _parse_dt(j.get("scheduled_date")) or datetime.max.replace(tzinfo=timezone.utc)
        return (cdt, sdt, str(j.get("id") or ""))
    return str(sorted(group, key=_key)[0].get("id") or "")


def _group_a_recurring(jobs: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Bucket jobs by ``recurring_template_id``.  ``None`` / empty
    template IDs are NOT grouped — they're one-off jobs by
    definition."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for j in jobs:
        tpl = j.get("recurring_template_id")
        if not tpl:
            continue
        buckets.setdefault(str(tpl), []).append(j)
    return [g for g in buckets.values() if len(g) >= 2]


def _group_b_exact(
    jobs: List[Dict[str, Any]], claimed: set,
) -> List[List[Dict[str, Any]]]:
    """Bucket un-claimed jobs by ``(scheduled_date_string, title)``.
    Uses the raw stored ``scheduled_date`` string for exact-match
    semantics — a 2026-01-15 job at 09:00 and 09:00:00 in different
    stores would tie here, which is the intent."""
    buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for j in jobs:
        if j.get("id") in claimed:
            continue
        sd = str(j.get("scheduled_date") or "").strip()
        title = str(j.get("title") or "").strip().lower()
        if not sd or not title:
            continue
        buckets.setdefault((sd, title), []).append(j)
    return [g for g in buckets.values() if len(g) >= 2]


def _group_c_near_adjacent(
    jobs: List[Dict[str, Any]], claimed: set,
) -> List[List[Dict[str, Any]]]:
    """Cluster jobs sharing the same ``title`` whose
    ``scheduled_date`` is within ``FUZZY_WINDOW_SECONDS`` of a
    peer.  Runs a simple sorted-scan clustering pass per title —
    jobs that fall inside the window of any previous cluster
    member roll into that cluster."""
    # Group first by lowered title so clusters can't cross services.
    by_title: Dict[str, List[Dict[str, Any]]] = {}
    for j in jobs:
        if j.get("id") in claimed:
            continue
        sdt = _parse_dt(j.get("scheduled_date"))
        if not sdt:
            continue
        title = str(j.get("title") or "").strip().lower()
        if not title:
            continue
        by_title.setdefault(title, []).append((sdt, j))

    clusters: List[List[Dict[str, Any]]] = []
    for _title, entries in by_title.items():
        entries.sort(key=lambda pair: pair[0])
        current: List[Dict[str, Any]] = []
        anchor: Optional[datetime] = None
        for sdt, j in entries:
            if anchor is None or (sdt - anchor).total_seconds() > FUZZY_WINDOW_SECONDS:
                if len(current) >= 2:
                    clusters.append(current)
                current = [j]
                anchor = sdt
            else:
                current.append(j)
        if len(current) >= 2:
            clusters.append(current)
    return clusters


def identify_duplicate_groups(
    jobs: List[Dict[str, Any]],
) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
    """Full detection pipeline for a single customer's jobs.

    Returns a list of ``(group_id, group_type, [job, …])`` tuples,
    where ``group_type`` is ``"A"`` / ``"B"`` / ``"C"`` and
    ``group_id`` is a deterministic UUID synthesised from the group's
    sorted member IDs so reruns produce the same CSV row keys.
    """
    claimed: set = set()
    out: List[Tuple[str, str, List[Dict[str, Any]]]] = []

    for group in _group_a_recurring(jobs):
        gid = _synthesise_group_id("A", [str(j.get("id")) for j in group])
        out.append((gid, "A", group))
        for j in group:
            claimed.add(j.get("id"))

    for group in _group_b_exact(jobs, claimed):
        gid = _synthesise_group_id("B", [str(j.get("id")) for j in group])
        out.append((gid, "B", group))
        for j in group:
            claimed.add(j.get("id"))

    for group in _group_c_near_adjacent(jobs, claimed):
        gid = _synthesise_group_id("C", [str(j.get("id")) for j in group])
        out.append((gid, "C", group))
        for j in group:
            claimed.add(j.get("id"))

    return out


def _synthesise_group_id(prefix: str, ids: List[str]) -> str:
    """Deterministic group ID = ``<prefix>-<uuid5(sorted-ids)>[:8]``
    so re-runs against unchanged data emit identical row keys —
    makes the CSV diff-friendly."""
    seed = "|".join(sorted(ids))
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:8]}"


# ═════════════════════════════════════════════════════════════════
# Row shaping
# ═════════════════════════════════════════════════════════════════
CSV_FIELDS = [
    "group_id", "group_type", "action", "tenant_id",
    "customer_id", "customer_name",
    "job_id", "scheduled_date", "title",
    "recurring_template_id", "status", "deleted_at", "created_at",
    "reasoning",
]


def _row(customer: Dict[str, Any], job: Dict[str, Any],
         group_id: str, group_type: str, action: str,
         reasoning: str) -> Dict[str, Any]:
    return {
        "group_id":              group_id,
        "group_type":            group_type,
        "action":                action,
        "tenant_id":             customer.get("tenant_id") or job.get("tenant_id") or "",
        "customer_id":           customer.get("id") or job.get("customer_id") or "",
        "customer_name":         customer.get("name")
                                    or f"{customer.get('first_name') or ''} "
                                       f"{customer.get('last_name') or ''}".strip(),
        "job_id":                job.get("id") or "",
        "scheduled_date":        job.get("scheduled_date") or "",
        "title":                 job.get("title") or "",
        "recurring_template_id": job.get("recurring_template_id") or "",
        "status":                job.get("status") or "",
        "deleted_at":            job.get("deleted_at") or "",
        "created_at":            job.get("created_at") or "",
        "reasoning":             reasoning,
    }


def build_csv_rows(customer: Dict[str, Any],
                   groups: List[Tuple[str, str, List[Dict[str, Any]]]],
                   ) -> List[Dict[str, Any]]:
    """Expand duplicate groups into one CSV row per job.  KEEP row
    always precedes its peers so a human scanning the CSV sees the
    survivor first."""
    reasons_by_type = {
        "A": "recurring occurrence — same recurring_template_id",
        "B": "exact scheduled_date + title match",
        "C": "near-adjacent (within ±5 min) same-title clone",
    }
    rows: List[Dict[str, Any]] = []
    for gid, gtype, group in groups:
        reason = reasons_by_type.get(gtype, "duplicate")
        keep_id = _select_keep_id(group)
        # Sort: KEEP first, then rest by created_at for stable output.
        def _sort_key(j):
            is_keep = 0 if str(j.get("id")) == keep_id else 1
            cdt = _parse_dt(j.get("created_at")) or datetime.max.replace(tzinfo=timezone.utc)
            return (is_keep, cdt, str(j.get("id") or ""))
        for j in sorted(group, key=_sort_key):
            action = "KEEP" if str(j.get("id")) == keep_id else "CANDIDATE_DELETE"
            note = f"Group {gtype} · {reason} · earliest created_at wins"
            rows.append(_row(customer, j, gid, gtype, action, note))
    return rows


# ═════════════════════════════════════════════════════════════════
# Mongo I/O — thin wrappers so tests can inject a fake ``db``
# ═════════════════════════════════════════════════════════════════
def _customer_query(name: Optional[str], tenant_id: Optional[str]) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if name:
        # Substring, case-insensitive.  Match across the three
        # common shapes (``name``, ``full_name``, split first/last).
        rx = re.escape(name.strip())
        name_regex = {"$regex": rx, "$options": "i"}
        q["$or"] = [
            {"name":       name_regex},
            {"full_name":  name_regex},
            {"first_name": name_regex},
            {"last_name":  name_regex},
        ]
    return q


def load_customers(db, name: Optional[str],
                   tenant_id: Optional[str]) -> List[Dict[str, Any]]:
    return list(db.customers.find(_customer_query(name, tenant_id)))


def load_jobs_for_customer(db, customer: Dict[str, Any]) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"customer_id": customer.get("id")}
    if customer.get("tenant_id"):
        q["tenant_id"] = customer["tenant_id"]
    return list(db.jobs.find(q))


# ═════════════════════════════════════════════════════════════════
# CSV writer + summariser
# ═════════════════════════════════════════════════════════════════
def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _summary_line(customer_count: int, job_count: int,
                  candidate_count: int, group_count: int) -> str:
    return (
        f"Found {customer_count} customer(s), {job_count} jobs total, "
        f"{candidate_count} candidate deletes across {group_count} "
        f"duplicate groups."
    )


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="preview_duplicate_jobs",
        description=(
            "Preview duplicate jobs — read-only.  Emits a CSV the "
            "operator reviews before running delete_duplicate_jobs.py."
        ),
    )
    p.add_argument("--customer-name", default=os.environ.get("DEDUP_CUSTOMER_NAME"))
    p.add_argument("--tenant-id",     default=os.environ.get("DEDUP_TENANT_ID"))
    p.add_argument(
        "--output",
        default=os.environ.get("DEDUP_OUTPUT_CSV", "duplicate_jobs_preview.csv"),
    )
    return p


def main(argv: Optional[List[str]] = None, *, db=None) -> int:
    args = _build_argparser().parse_args(argv)
    if db is None:  # pragma: no cover — real Mongo path exercised by ops
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        if not mongo_url or not db_name:
            print("ERROR: MONGO_URL and DB_NAME env vars required.", file=sys.stderr)
            return 2
        db = MongoClient(mongo_url)[db_name]

    customers = load_customers(db, args.customer_name, args.tenant_id)
    all_rows: List[Dict[str, Any]] = []
    total_jobs = 0
    total_groups = 0
    total_candidates = 0
    for c in customers:
        jobs = load_jobs_for_customer(db, c)
        total_jobs += len(jobs)
        groups = identify_duplicate_groups(jobs)
        total_groups += len(groups)
        rows = build_csv_rows(c, groups)
        total_candidates += sum(1 for r in rows if r["action"] == "CANDIDATE_DELETE")
        all_rows.extend(rows)

    write_csv(args.output, all_rows)
    print(_summary_line(
        customer_count=len(customers),
        job_count=total_jobs,
        candidate_count=total_candidates,
        group_count=total_groups,
    ))
    print(f"CSV written to: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
