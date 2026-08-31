"""Feb-2026 · Phase F2 addendum · services/authz.py exception logging.

Contract: when the crews-lookup ``find_one`` raises, the helper
still returns ``False`` (fail-closed) BUT it now emits an
ERROR-level log with the specific exception so ops sees a Mongo
blip instead of a silent 403 wave. Prior to F2 the branch swallowed
every exception with no log line at all.
"""
from __future__ import annotations

import asyncio
import logging

from services.authz import is_tech_authorized_on_job


class _BoomCollection:
    async def find_one(self, *_a, **_k):  # noqa: ARG002
        raise RuntimeError("motor exploded")


class _BoomDB:
    crews = _BoomCollection()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_authz_logs_error_and_returns_false(caplog):
    user = {"id": "user-a", "role": "technician",
            "technician_id": "tech-a"}
    job = {"technician_id": None, "crew_id": "crew-1", "tenant_id": "t1"}

    with caplog.at_level(logging.ERROR, logger="services.authz"):
        result = _run(is_tech_authorized_on_job(user, job, _BoomDB()))

    # Fail-closed: still False.
    assert result is False

    # And one ERROR record with the expected context fields.
    records = [r for r in caplog.records
               if r.name == "services.authz" and r.levelno == logging.ERROR]
    assert len(records) == 1, (
        f"expected 1 ERROR log from services.authz, got {len(records)}"
    )
    msg = records[0].getMessage()
    for token in ("crew_id=crew-1", "tenant_id=t1", "motor exploded"):
        assert token in msg, (
            f"log missing expected token {token!r}; full msg: {msg!r}"
        )
