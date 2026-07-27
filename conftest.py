"""Repo-root pytest bootstrap for tests that live under ``backend/``.

Lets ``pytest`` be invoked from ``/app`` (``pytest backend/tests/...``)
without requiring ``PYTHONPATH=/app/backend`` on every call. Backend
modules are imported via ``services.marketing.merge_tags``,
``services.email.resend_adapter`` etc. — this ``conftest.py`` prepends
``/app/backend`` to ``sys.path`` so those imports resolve.

This complements ``backend/pytest.ini``'s ``pythonpath = .`` which
covers the ``cd /app/backend && pytest`` case; this file covers the
``cd /app && pytest backend/tests/...`` case.
"""
from __future__ import annotations

import os
import sys

_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
