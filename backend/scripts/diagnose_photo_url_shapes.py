"""TD-76-aux · Feb-2026 — READ-ONLY photo URL shape diagnostic.

Scans ``jobs.photos[]`` and ``estimates.photos[]`` across every
tenant in the configured MongoDB and classifies the ``url`` field
by shape.  Writes a timestamped summary to
``/app/memory/photo_url_shape_diagnostic.md``.

**Pure read.** No writes.  No ``--apply`` flag.  This is pure
Phase B scoping data — do NOT add a mutate path.

Usage:
    cd /app/backend && python -m scripts.diagnose_photo_url_shapes

Operator note: ``--dry-run`` is implicit (the only mode).  Preview
or prod DB — defaults to whatever ``MONGO_URL`` the service is
pointed at.  For prod reads, operator should run the script with
a prod ``MONGO_URL`` env var manually (not covered by any CI).
"""
from __future__ import annotations

import asyncio
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "pool_crm")

# Classification regexes — documented so Phase B knows what we matched.
_RE_HTTP = re.compile(r"^https?://", re.IGNORECASE)
_RE_RELATIVE_API = re.compile(r"^/api/")
# Storage-path heuristic — tenant/entity/file-ish paths with no leading slash.
_RE_STORAGE_PATH = re.compile(
    r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9._/-]+$"
)
# S3-key heuristic — the Phase-27 upload path writes keys like
# ``Photos/<tenant>/<uuid>.jpg`` with no leading slash and a known prefix.
_RE_S3_KEY = re.compile(
    r"^(Photos|photos|Videos|videos|media|Media)/", re.IGNORECASE
)


def classify_url(value) -> str:
    if value is None or value == "":
        return "empty_or_null"
    if not isinstance(value, str):
        return "other"
    if _RE_HTTP.match(value):
        return "valid_http"
    if _RE_RELATIVE_API.match(value):
        return "relative_api"
    if _RE_S3_KEY.match(value):
        return "raw_s3_key"
    if _RE_STORAGE_PATH.match(value):
        return "raw_storage_path"
    return "other"


async def scan():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Aggregates.
    results = {"jobs": _bucket(), "estimates": _bucket()}
    # Per-tenant breakdown.
    tenant_counts = {"jobs": defaultdict(Counter),
                      "estimates": defaultdict(Counter)}
    # Sample stash for "other" category — up to 6 per collection.
    samples = {"jobs": [], "estimates": []}

    async def _scan_coll(coll_name):
        coll = db[coll_name]
        async for doc in coll.find({}, {
            "tenant_id": 1, "photos": 1, "_id": 0,
        }):
            tenant = doc.get("tenant_id") or "unknown"
            for p in (doc.get("photos") or []):
                if not isinstance(p, dict):
                    continue
                shape = classify_url(p.get("url"))
                results[coll_name]["url_shape"][shape] += 1
                tenant_counts[coll_name][tenant][shape] += 1
                if shape == "other" and len(samples[coll_name]) < 6:
                    samples[coll_name].append(
                        {"tenant": tenant,
                          "url": str(p.get("url"))[:120]}
                    )
                # Adjacency counters.
                if p.get("storage_path"):
                    results[coll_name]["adjacency"]["has_storage_path"] += 1
                if p.get("thumb"):
                    results[coll_name]["adjacency"]["has_thumb"] += 1
                if (not p.get("storage_path") and not p.get("thumb")):
                    results[coll_name]["adjacency"]["neither_storage_nor_thumb"] += 1
                results[coll_name]["total"] += 1

    await _scan_coll("jobs")
    await _scan_coll("estimates")

    return results, tenant_counts, samples


def _bucket():
    return {
        "total": 0,
        "url_shape": Counter(),
        "adjacency": Counter(),
    }


def _top_tenants(tenant_counts, k=5):
    scored = [
        (tenant, sum(c.values()),
          c.get("raw_storage_path", 0) + c.get("raw_s3_key", 0)
            + c.get("empty_or_null", 0) + c.get("other", 0))
        for tenant, c in tenant_counts.items()
    ]
    # Rank by "problematic" count DESC, then total DESC.
    scored.sort(key=lambda t: (-t[2], -t[1]))
    return scored[:k]


def render(results, tenant_counts, samples):
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# TD-76-aux · Photo URL Shape Diagnostic",
        "",
        f"**Run at:** {now}",
        f"**MONGO_URL:** `{_mask(MONGO_URL)}`",
        f"**DB:** `{DB_NAME}`",
        "",
        "**READ-ONLY.** No writes performed. Pure Phase B scoping data.",
        "",
        "## Classification regexes",
        "",
        "| Shape | Regex |",
        "|---|---|",
        f"| `valid_http` | `{_RE_HTTP.pattern}` |",
        f"| `relative_api` | `{_RE_RELATIVE_API.pattern}` |",
        f"| `raw_s3_key` | `{_RE_S3_KEY.pattern}` |",
        f"| `raw_storage_path` | `{_RE_STORAGE_PATH.pattern}` |",
        "| `empty_or_null` | missing / `None` / `\"\"` |",
        "| `other` | everything else (sampled below) |",
        "",
    ]
    for coll in ("jobs", "estimates"):
        bucket = results[coll]
        lines += [
            f"## `{coll}.photos[]` (total subdocs: {bucket['total']})",
            "",
            "**URL shape counts:**",
            "",
            "| Shape | Count |",
            "|---|---|",
        ]
        for shape in ("valid_http", "relative_api", "raw_s3_key",
                      "raw_storage_path", "empty_or_null", "other"):
            lines.append(f"| `{shape}` | {bucket['url_shape'].get(shape, 0)} |")
        lines += [
            "",
            "**Adjacent-field counts:**",
            "",
            "| Adjacency | Count |",
            "|---|---|",
            f"| `has_storage_path` | {bucket['adjacency'].get('has_storage_path', 0)} |",
            f"| `has_thumb`        | {bucket['adjacency'].get('has_thumb', 0)} |",
            f"| `neither_storage_nor_thumb` | {bucket['adjacency'].get('neither_storage_nor_thumb', 0)} |",
            "",
        ]
        top = _top_tenants(tenant_counts[coll])
        if top:
            lines += [
                "**Top-5 tenants by problematic count:**",
                "",
                "| Tenant | Total photos | Problematic (raw_s3_key + raw_storage_path + empty + other) |",
                "|---|---|---|",
            ]
            for tenant, total, prob in top:
                lines.append(f"| `{tenant}` | {total} | {prob} |")
            lines.append("")
        if samples[coll]:
            lines += ["**`other` samples:**", "", "```"]
            for s in samples[coll]:
                lines.append(f"- tenant={s['tenant']}  url={s['url']}")
            lines += ["```", ""]
    return "\n".join(lines)


def _mask(url: str) -> str:
    # Strip credentials from the MONGO_URL for the writeup.
    return re.sub(r"://[^@]+@", "://***:***@", url)


async def main():
    results, tenant_counts, samples = await scan()
    md = render(results, tenant_counts, samples)
    out = Path("/app/memory/photo_url_shape_diagnostic.md")
    out.write_text(md)
    print(f"Wrote {out} ({len(md)} bytes).")


if __name__ == "__main__":
    asyncio.run(main())
