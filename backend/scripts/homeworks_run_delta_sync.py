#!/usr/bin/env python3
"""Queue Item 5 · Feb-2026 — Delta-sync launcher.

Runs the ``delta_sync_importer.run_full`` driver in the current
process, honouring the run doc created by ``POST /run``. Intended
for ``nohup`` invocation from an operator shell (same pattern as
``homeworks_run_import.py`` and ``homeworks_run_active_import.py``).

Usage::

    nohup python3 -m scripts.homeworks_run_delta_sync \\
        --tenant-id <uuid> \\
        --run-id   <hex> \\
        >> /var/log/homeworks_delta_sync.log 2>&1 &
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


def _emit(evt: str, **kw) -> None:
    doc = {"at": datetime.now(timezone.utc).isoformat(), "evt": evt, **kw}
    print(json.dumps(doc, default=str), flush=True)


async def _run(tenant_id: str, run_id: str, user_id: str | None) -> int:
    from services.homeworks_mcp import delta_sync_importer as imp
    _emit("boot", tenant_id=tenant_id, run_id=run_id)
    try:
        counters = await imp.run_full(
            tenant_id=tenant_id, user_id=user_id, run_id=run_id,
        )
    except Exception as exc:  # noqa: BLE001
        _emit("crash", error=str(exc)[:500])
        return 3
    _emit("done", counters=counters)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--user-id", default=None,
                     help="Optional actor for audit trail.")
    args = ap.parse_args()
    return asyncio.run(_run(args.tenant_id, args.run_id, args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
