"""Phase P35 · Feb-2026 — S3 photo backfill migration.

Two independent, idempotent passes over ``jobs.photos[]``:

  * **Pass A — reprefix ``job-photos/`` → ``Photos/``.**  Reads the
    legacy S3 object, PUTs it under the canonical prefix (via the
    shared ``services.aws_s3.photos.build_key`` helper — no
    hand-rolled key shapes), updates the DB row, then deletes the
    old S3 object.  Photos already under the canonical prefix are
    silently skipped.

  * **Pass B — base64 → S3 for rows missing ``s3_key``.**  Decodes
    ``photo.data`` (a data URL of the form
    ``data:<mime>;base64,<blob>``), uploads to ``Photos/`` via the
    shared key builder, and stamps ``photo.s3_key`` + ``photo.s3_mime``
    on the DB row.  **Leaves ``photo.data`` in place** — the P35
    renderer ladder still reads it as a safety net.

CLI (dry-run is the default so an accidental invocation cannot mutate)::

    python -m scripts.p35_photo_backfill [--execute]
                                          [--pass=a|b|both]
                                          [--batch=100]
                                          [--tenant=<id>]
                                          [--limit=<N>]

End-of-run summary is emitted as a single-line JSON blob on stdout::

    {"pass_a": {...counts...}, "pass_b": {...counts...},
     "duration_s": ..., "dry_run": true|false}

The script is safe to re-run: pass-A skips photos whose ``s3_key``
already starts with the canonical prefix, and pass-B skips photos
that already carry an ``s3_key``.  Every S3 PUT is HEAD-checked
first so an already-migrated key isn't re-uploaded.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────
# Env bootstrap — same pattern the rest of the backend uses. The
# script is imported as a module (``python -m scripts.p35_photo_backfill``)
# so ``config.db`` is the DB handle we want to mutate.
# ─────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


from config import db, logger  # noqa: E402  (env loaded above)

# ``PRE_P35_PREFIX`` is the legacy prefix pass-A rewrites away
# from. The canonical destination prefix is taken from the shared
# key builder (see ``services.aws_s3.photos.build_key``), which
# reads ``AWS_S3_PREFIX`` from env.
PRE_P35_PREFIX = "job-photos/"

# Rate-limit PUTs to ~50/s to stay well under S3 quota. This is
# per-worker (single-process script) so global request rate is
# ~50/s even for large batches.
_S3_PUT_RATE_PER_SEC = 50.0
_S3_PUT_MIN_INTERVAL_S = 1.0 / _S3_PUT_RATE_PER_SEC


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="p35_photo_backfill",
        description="P35 · S3 photo backfill migration (idempotent).",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help=("Actually mutate S3 + DB. Default is dry-run "
              "(no mutations)."),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=("Explicit dry-run flag — accepted as a no-op alias for "
              "the default behaviour. Mutually incompatible with "
              "``--execute``; if both are passed we raise."),
    )
    p.add_argument(
        "--pass", dest="which_pass",
        choices=("a", "b", "both"), default="both",
        help="Which pass to run. Default: both.",
    )
    p.add_argument(
        "--batch", type=int, default=100,
        help=("Batch size — the script yields progress every N "
              "processed photos. Default: 100."),
    )
    p.add_argument(
        "--tenant", type=str, default=None,
        help=("Optional tenant filter — only touch photos belonging "
              "to this tenant_id."),
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help=("Optional cap on total photos processed per pass "
              "(useful for canary runs). Default: unlimited."),
    )
    return p


# ─────────────────────────────────────────────────────────────────
# Rate-limiter (async-friendly)
# ─────────────────────────────────────────────────────────────────
class _RateLimiter:
    def __init__(self, min_interval_s: float) -> None:
        self._min = float(min_interval_s)
        self._last = 0.0

    async def tick(self) -> None:
        now = time.monotonic()
        wait = (self._last + self._min) - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.monotonic()


# ─────────────────────────────────────────────────────────────────
# Data-URL parsing — same shape ``services.aws_s3.photos.decode_data_url``
# emits but re-implemented locally so the migration doesn't need the
# S3 helper to be importable during a dry-run.
# ─────────────────────────────────────────────────────────────────
_DATA_URL_RE = re.compile(r"^data:([^;,]+)(?:;[^,]*)?,(.*)$", re.DOTALL)


def _parse_data_url(data_url: str) -> Optional[tuple[bytes, str]]:
    """Return ``(bytes, mime)`` on success, ``None`` on failure."""
    if not isinstance(data_url, str) or not data_url:
        return None
    m = _DATA_URL_RE.match(data_url)
    if m:
        mime = (m.group(1) or "").strip() or "image/jpeg"
        payload = m.group(2) or ""
    elif "," in data_url:
        header, payload = data_url.split(",", 1)
        mime = "image/jpeg"
        if header.startswith("data:"):
            mp = header[len("data:"):].split(";", 1)[0]
            if mp:
                mime = mp
    else:
        payload, mime = data_url, "image/jpeg"
    try:
        return base64.b64decode(payload), mime
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# Pass A — reprefix ``job-photos/`` → canonical ``Photos/``
# ─────────────────────────────────────────────────────────────────
async def _run_pass_a(*, execute: bool, batch: int,
                       tenant_filter: Optional[str],
                       limit: Optional[int]) -> Dict[str, Any]:
    from services.aws_s3.photos import (
        build_key, check_object_exists, read_object,
        upload_blob_at_key, delete_photo, _cfg,
    )
    cfg = _cfg()
    canonical_prefix = (cfg.get("prefix") or "").strip() or "Photos/"
    if not canonical_prefix.endswith("/"):
        canonical_prefix = canonical_prefix + "/"

    counters = {
        "scanned_jobs": 0,
        "scanned_photos": 0,
        "candidates": 0,
        "reprefixed": 0,
        "reprefixed_via_base64_repair": 0,
        "skipped_already_canonical": 0,
        "skipped_s3_miss_on_old_key": 0,
        "skipped_put_failed": 0,
        "skipped_db_update_failed": 0,
        "skipped_old_delete_failed": 0,
        "failed_other": 0,
    }
    unresolvable: List[Dict[str, Any]] = []
    limiter = _RateLimiter(_S3_PUT_MIN_INTERVAL_S)

    query: Dict[str, Any] = {"photos.s3_key": {"$regex": f"^{PRE_P35_PREFIX}"}}
    if tenant_filter:
        query["tenant_id"] = tenant_filter

    cursor = db.jobs.find(
        query,
        {"_id": 0, "id": 1, "tenant_id": 1, "photos": 1},
    )
    processed_total = 0
    async for job in cursor:
        counters["scanned_jobs"] += 1
        jid = job.get("id")
        tid = job.get("tenant_id")
        photos = job.get("photos") or []
        for photo in photos:
            counters["scanned_photos"] += 1
            if not isinstance(photo, dict):
                continue
            old_key = photo.get("s3_key") or ""
            if not old_key.startswith(PRE_P35_PREFIX):
                # Skip the sibling photos on the same job that are
                # already canonical — pass-A only rewrites the legacy
                # prefix rows.
                if old_key.startswith(canonical_prefix):
                    counters["skipped_already_canonical"] += 1
                continue
            counters["candidates"] += 1
            processed_total += 1
            if limit is not None and processed_total > limit:
                logger.info(
                    "[p35 pass-a] limit=%s reached, stopping.", limit,
                )
                break
            pid = photo.get("id") or ""
            mime = (photo.get("s3_mime") or "image/jpeg").strip()
            try:
                new_key = build_key(tid, jid, pid, prefix=canonical_prefix)
            except Exception as exc:
                logger.warning(
                    "[p35 pass-a] key build failed jid=%s pid=%s err=%s",
                    jid, pid, exc,
                )
                counters["failed_other"] += 1
                unresolvable.append({
                    "reason": "key_build_failed",
                    "job_id": jid, "photo_id": pid, "old_key": old_key,
                })
                continue
            if new_key == old_key:
                # Legacy prefix happened to be identical to canonical
                # — degenerate no-op.
                counters["skipped_already_canonical"] += 1
                continue
            # Dry-run stops here — just count the candidate.
            if not execute:
                counters["reprefixed"] += 1
                continue
            # Execute path — HEAD (idempotency), copy, DB update, delete.
            if check_object_exists(new_key):
                # Someone already migrated this key — just flip the
                # DB row and skip the S3 PUT.
                res = await db.jobs.update_one(
                    {"id": jid, "photos.id": pid},
                    {"$set": {"photos.$.s3_key": new_key}},
                )
                if res.matched_count:
                    counters["reprefixed"] += 1
                else:
                    counters["skipped_db_update_failed"] += 1
                # Attempt best-effort delete of old key too.
                if not delete_photo(old_key):
                    counters["skipped_old_delete_failed"] += 1
                    unresolvable.append({
                        "reason": "old_delete_failed",
                        "job_id": jid, "photo_id": pid,
                        "old_key": old_key, "new_key": new_key,
                    })
                continue
            # Read the old S3 object.
            blob = read_object(old_key)
            if blob is None:
                # Orphaned old key — the DB says the object lives at
                # ``job-photos/...`` but S3 no longer has it (pre-P35
                # bucket cleanup, cross-region drift, whatever).
                # If the sub-doc still carries the ``data`` data URL
                # we can repair from base64 into the canonical key —
                # equivalent outcome to a pass-B upload, but scoped
                # here because pass-B's query only matches empty
                # ``s3_key`` rows.
                data_url = photo.get("data") or ""
                decoded = _parse_data_url(data_url) if data_url else None
                if decoded is None:
                    counters["skipped_s3_miss_on_old_key"] += 1
                    unresolvable.append({
                        "reason": "s3_miss_on_old_key",
                        "job_id": jid, "photo_id": pid,
                        "old_key": old_key,
                    })
                    continue
                blob, mime_from_data = decoded
                # Prefer the on-doc s3_mime; fall back to the data-URL
                # mime so the S3 Content-Type is truthful.
                if mime_from_data and mime == "image/jpeg":
                    mime = mime_from_data
                await limiter.tick()
                put_key = upload_blob_at_key(new_key, blob, mime)
                if put_key is None:
                    counters["skipped_put_failed"] += 1
                    unresolvable.append({
                        "reason": "put_failed_after_base64_repair",
                        "job_id": jid, "photo_id": pid,
                        "old_key": old_key, "new_key": new_key,
                    })
                    continue
                # DB stamp — s3_key flips to canonical; s3_mime tracked
                # so the renderer serves the right Content-Type on any
                # future base64 fallback.
                try:
                    res = await db.jobs.update_one(
                        {"id": jid, "photos.id": pid},
                        {"$set": {
                            "photos.$.s3_key": new_key,
                            "photos.$.s3_mime": mime,
                        }},
                    )
                except Exception as exc:
                    logger.warning(
                        "[p35 pass-a] repair DB update failed "
                        "jid=%s pid=%s err=%s",
                        jid, pid, exc,
                    )
                    counters["skipped_db_update_failed"] += 1
                    unresolvable.append({
                        "reason": "db_update_failed_after_base64_repair",
                        "job_id": jid, "photo_id": pid,
                        "old_key": old_key, "new_key": new_key,
                    })
                    continue
                if not res.matched_count:
                    counters["skipped_db_update_failed"] += 1
                    unresolvable.append({
                        "reason": "db_update_no_match_after_base64_repair",
                        "job_id": jid, "photo_id": pid,
                        "old_key": old_key, "new_key": new_key,
                    })
                    continue
                counters["reprefixed_via_base64_repair"] += 1
                logger.info(
                    "[p35 pass-a] repaired via base64 jid=%s pid=%s new_key=%s",
                    jid, pid, new_key,
                )
                continue
            await limiter.tick()
            put_key = upload_blob_at_key(new_key, blob, mime)
            if put_key is None:
                counters["skipped_put_failed"] += 1
                unresolvable.append({
                    "reason": "put_failed",
                    "job_id": jid, "photo_id": pid,
                    "old_key": old_key, "new_key": new_key,
                })
                continue
            # DB update — positional on ``photos.id`` so we only touch
            # the target sub-doc.
            try:
                res = await db.jobs.update_one(
                    {"id": jid, "photos.id": pid},
                    {"$set": {"photos.$.s3_key": new_key}},
                )
            except Exception as exc:
                logger.warning(
                    "[p35 pass-a] DB update failed jid=%s pid=%s err=%s",
                    jid, pid, exc,
                )
                counters["skipped_db_update_failed"] += 1
                unresolvable.append({
                    "reason": "db_update_failed",
                    "job_id": jid, "photo_id": pid,
                    "old_key": old_key, "new_key": new_key,
                })
                continue
            if not res.matched_count:
                counters["skipped_db_update_failed"] += 1
                unresolvable.append({
                    "reason": "db_update_no_match",
                    "job_id": jid, "photo_id": pid,
                    "old_key": old_key, "new_key": new_key,
                })
                continue
            counters["reprefixed"] += 1
            # Delete the old S3 object AFTER the DB is confirmed. A
            # delete failure is non-fatal — sweep as a follow-up.
            if not delete_photo(old_key):
                counters["skipped_old_delete_failed"] += 1
                unresolvable.append({
                    "reason": "old_delete_failed",
                    "job_id": jid, "photo_id": pid,
                    "old_key": old_key, "new_key": new_key,
                })
            # Per-batch progress log.
            if counters["candidates"] and counters["candidates"] % batch == 0:
                logger.info(
                    "[p35 pass-a] batch=%s processed=%s succeeded=%s "
                    "skipped=%s failed=%s",
                    counters["candidates"] // batch,
                    counters["candidates"],
                    counters["reprefixed"],
                    (counters["skipped_already_canonical"]
                     + counters["skipped_s3_miss_on_old_key"]),
                    (counters["skipped_put_failed"]
                     + counters["skipped_db_update_failed"]
                     + counters["skipped_old_delete_failed"]
                     + counters["failed_other"]),
                )
        if limit is not None and processed_total >= limit:
            break

    return {"counters": counters, "unresolvable": unresolvable,
            "canonical_prefix": canonical_prefix}


# ─────────────────────────────────────────────────────────────────
# Pass B — base64 → S3 for rows missing ``s3_key``
# ─────────────────────────────────────────────────────────────────
async def _run_pass_b(*, execute: bool, batch: int,
                       tenant_filter: Optional[str],
                       limit: Optional[int]) -> Dict[str, Any]:
    from services.aws_s3.photos import (
        build_key, check_object_exists, upload_blob_at_key, _cfg,
    )
    cfg = _cfg()
    canonical_prefix = (cfg.get("prefix") or "").strip() or "Photos/"
    if not canonical_prefix.endswith("/"):
        canonical_prefix = canonical_prefix + "/"

    counters = {
        "scanned_jobs": 0,
        "scanned_photos": 0,
        "candidates": 0,
        "uploaded": 0,
        "skipped_decode_failed": 0,
        "skipped_put_failed": 0,
        "skipped_db_update_failed": 0,
        "failed_other": 0,
    }
    unresolvable: List[Dict[str, Any]] = []
    limiter = _RateLimiter(_S3_PUT_MIN_INTERVAL_S)

    query: Dict[str, Any] = {
        "photos": {"$elemMatch": {
            "data": {"$exists": True, "$nin": [None, ""]},
            "$or": [
                {"s3_key": {"$exists": False}},
                {"s3_key": None},
                {"s3_key": ""},
            ],
        }},
    }
    if tenant_filter:
        query["tenant_id"] = tenant_filter

    cursor = db.jobs.find(
        query,
        {"_id": 0, "id": 1, "tenant_id": 1, "photos": 1},
    )
    processed_total = 0
    async for job in cursor:
        counters["scanned_jobs"] += 1
        jid = job.get("id")
        tid = job.get("tenant_id")
        photos = job.get("photos") or []
        for photo in photos:
            counters["scanned_photos"] += 1
            if not isinstance(photo, dict):
                continue
            s3_key = photo.get("s3_key") or ""
            data_url = photo.get("data") or ""
            if s3_key or not data_url:
                # This sub-photo isn't a pass-B candidate.
                continue
            counters["candidates"] += 1
            processed_total += 1
            if limit is not None and processed_total > limit:
                logger.info(
                    "[p35 pass-b] limit=%s reached, stopping.", limit,
                )
                break
            pid = photo.get("id") or ""
            decoded = _parse_data_url(data_url)
            if decoded is None:
                counters["skipped_decode_failed"] += 1
                unresolvable.append({
                    "reason": "decode_failed",
                    "job_id": jid, "photo_id": pid,
                })
                continue
            blob, mime = decoded
            try:
                new_key = build_key(tid, jid, pid, prefix=canonical_prefix)
            except Exception as exc:
                counters["failed_other"] += 1
                unresolvable.append({
                    "reason": "key_build_failed",
                    "job_id": jid, "photo_id": pid, "err": str(exc),
                })
                continue
            if not execute:
                counters["uploaded"] += 1
                continue
            # HEAD check for idempotency.
            if not check_object_exists(new_key):
                await limiter.tick()
                put_key = upload_blob_at_key(new_key, blob, mime)
                if put_key is None:
                    counters["skipped_put_failed"] += 1
                    unresolvable.append({
                        "reason": "put_failed",
                        "job_id": jid, "photo_id": pid,
                        "new_key": new_key,
                    })
                    continue
            # DB stamp — leave ``data`` in place per P35 policy.
            try:
                res = await db.jobs.update_one(
                    {"id": jid, "photos.id": pid},
                    {"$set": {
                        "photos.$.s3_key": new_key,
                        "photos.$.s3_mime": mime,
                    }},
                )
            except Exception as exc:
                logger.warning(
                    "[p35 pass-b] DB update failed jid=%s pid=%s err=%s",
                    jid, pid, exc,
                )
                counters["skipped_db_update_failed"] += 1
                unresolvable.append({
                    "reason": "db_update_failed",
                    "job_id": jid, "photo_id": pid,
                    "new_key": new_key,
                })
                continue
            if not res.matched_count:
                counters["skipped_db_update_failed"] += 1
                unresolvable.append({
                    "reason": "db_update_no_match",
                    "job_id": jid, "photo_id": pid,
                    "new_key": new_key,
                })
                continue
            counters["uploaded"] += 1
            if counters["candidates"] and counters["candidates"] % batch == 0:
                logger.info(
                    "[p35 pass-b] batch=%s processed=%s succeeded=%s "
                    "skipped=%s failed=%s",
                    counters["candidates"] // batch,
                    counters["candidates"],
                    counters["uploaded"],
                    counters["skipped_decode_failed"],
                    (counters["skipped_put_failed"]
                     + counters["skipped_db_update_failed"]
                     + counters["failed_other"]),
                )
        if limit is not None and processed_total >= limit:
            break

    return {"counters": counters, "unresolvable": unresolvable,
            "canonical_prefix": canonical_prefix}


# ─────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────
async def _main_async(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.dry_run and args.execute:
        raise SystemExit(
            "--dry-run and --execute are mutually exclusive; pick one."
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    t0 = time.monotonic()
    logger.info(
        "[p35] starting migration (execute=%s pass=%s tenant=%s limit=%s) ...",
        args.execute, args.which_pass,
        args.tenant or "*", args.limit or "unlimited",
    )
    report: Dict[str, Any] = {
        "dry_run": not args.execute,
        "pass_a": None,
        "pass_b": None,
        "duration_s": 0.0,
    }
    if args.which_pass in ("a", "both"):
        report["pass_a"] = await _run_pass_a(
            execute=args.execute, batch=args.batch,
            tenant_filter=args.tenant, limit=args.limit,
        )
    if args.which_pass in ("b", "both"):
        report["pass_b"] = await _run_pass_b(
            execute=args.execute, batch=args.batch,
            tenant_filter=args.tenant, limit=args.limit,
        )
    report["duration_s"] = round(time.monotonic() - t0, 3)
    print(json.dumps(report, default=str))
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    sys.exit(main())
