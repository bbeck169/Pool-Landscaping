"""Shared module-scoped event loop for tests that touch Motor.

Motor's AsyncIOMotorClient attaches to whichever event loop it is
first used from. If two test files each create their own throwaway
loop, the second file's calls fail with "attached to a different loop"
errors because Motor is still bound to the FIRST loop.

Phase 10 + Phase 11 both need to exercise real Motor code paths, so
they now import ``LOOP`` from here instead of instantiating their own.
Any future test file that touches Motor should do the same."""
from __future__ import annotations

import asyncio

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def run(coro):
    return LOOP.run_until_complete(coro)
