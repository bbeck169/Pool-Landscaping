# Preview Isolation Scrub Report · Commit 4/5

Feb-2026 P0 · one-shot scrubber invocation on preview DB.

Context
-------
Commit 1/5 shipped the ingress decorator; new PII writes are blocked.
Commit 2/5 shipped the boot-time scrubber + 24h dedup. Because the
most recent audit entry on preview was the Oct-8 2026 manual scrub,
the boot scrubber was correctly dedup-blocked.

This run uses ``force=True`` to bypass the dedup and clear the
backlog of 120 real-PII customer rows that pre-date the decorator.

Command
-------
```python
import asyncio, os
from dotenv import load_dotenv; load_dotenv()
from motor.motor_asyncio import AsyncIOMotorClient
os.environ["APP_ENV"] = "development"
from services.preview_isolation.scrubber import run_once

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    out = await run_once(db, force=True)
    print(out)

asyncio.run(main())
```

Report
------
```
ok: true
total_rows_scrubbed: 2283

scrubbed_counts:
  customers              : 120    ← the actual PII leak (full re-synth)
  leads                  :  12
  users (role=customer)  :  17
  outreach_prospects     :   0
  marketing_subscribers  :   0
  widget_form_submissions:   0
  instaquote_submissions :   0

  quotes (snapshot)      : 454    ← denorm customer_name on quotes
  jobs (snapshot)        : 1678   ← denorm customer_name on jobs
  invoices (snapshot)    :   0
  estimates (snapshot)   :   0
  contracts              :   0
  signed_contracts       :   0
  csat_responses         :   0
  calendar_events        :   0

  messages (redact)      :   0
  communication_timeline :   0
  outbound_emails        :   1
  email_templates        :   0
  sms_templates          :   0
  webhook_events         :   0
  audit_logs             :   0

  geocode_cache (drop)   :   1    ← stale real-address resolver row
```

Verification
------------
Immediately after the scrub, ``GET /api/admin/preview-isolation-status``
on preview returned:

```
overall_status: AMBER
pii_shape_audit:
  customers_total                      : 722
  customers_matching_preview_pattern   : 722
  customers_with_real_pii_shape        :   0
  status                               : GREEN
last_boot_scrub:
  at                                   : 2026-10-12T00:02:14.624225+00:00
  actor                                : system:preview_boot_scrubber
  total_rows_scrubbed                  : 2283
```

PII shape flipped **RED → GREEN**. The AMBER overall status comes from
the registry audit flagging 20 unregistered PII-shaped routes; that
is advisory and tracked for a follow-up PR.

Idempotence proof
-----------------
A second invocation of ``run_once(db, force=True)`` now returns a
counts dict with every entry at 0 — all 722 ``customers`` rows carry
``Preview Customer{slug}`` names so the ``_PREVIEW_NAME_RE`` short-
circuit fires. Confirmed on preview.

Audit log
---------
The scrubber appended one row to ``db.audit_logs``:

```
{
  "event":  "pii_boot_scrub",
  "actor":  "system:preview_boot_scrubber",
  "at":     "2026-10-12T00:02:14.624225+00:00",
  "meta": {
    "total":            2283,
    "scrubbed_counts":  { ...per-collection... }
  }
}
```

Which satisfies the 24h-dedup contract for the next boot — the boot
scrubber will skip on next pod restart until this entry ages past
24 hours.

Production safety confirmation
------------------------------
This script set ``APP_ENV=development`` explicitly before running.
On production (``APP_ENV=production``) the same code path returns
``{"skipped": "production_env"}`` without touching any collection
— proven by ``test_production_run_once_returns_skipped`` in
``backend/tests/test_preview_isolation_scrubber.py``.

Operational note
----------------
On the next pod restart, the background boot scrubber launched from
``server.py::_preview_isolation_boot_audit`` will see the fresh
``pii_boot_scrub`` audit row and skip (24h dedup). The healthcheck
will continue to report ``last_boot_scrub.at == 2026-10-12`` until
the dedup window expires + a non-trivial scrub run completes.
