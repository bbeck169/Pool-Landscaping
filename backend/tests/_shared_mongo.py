"""Phase G3.1 · Feb-2026 — shared lazy Mongo singleton for pytest.

Historical context
-------------------
Every test file used to open its own module-level ``pymongo.MongoClient``
in a two-line block at import time::

    _sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

That was 250 files ⇒ up to 250 clients × ``maxPoolSize=100`` = 25 000
sockets opened during pytest collection, which reliably tripped
``ServerSelectionTimeoutError`` on late-suite full runs.

Fix
----
This module exposes a **single** lazily-instantiated ``MongoClient``
plus the corresponding ``Database`` handle for the whole session.
Every test file imports :func:`shared_db` (returns the ``Database``)
or :func:`shared_client` (returns the client) instead of opening its
own client.

Notes
-----
* Instantiation is lazy so ``import tests._shared_mongo`` in a
  fixture-free path is free — the client is only opened on first
  ``shared_db()`` call.
* The connection is process-scoped; each ``pytest`` run terminates
  the interpreter which closes the socket, so there's no explicit
  ``.close()`` here (matches conftest's own ``MongoClient`` usage in
  ``_purge_test_data`` / ``two_technicians`` before the migration).
* NEW TEST AUTHORS: DO NOT open module-level ``MongoClient()`` in a
  new test file. Import ``shared_db`` from this module and slice
  ``.collection_name`` as you normally would. See
  ``tests/conftest.py`` for the enforcement note.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from pymongo import MongoClient
from pymongo.database import Database


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")


_client: Optional[MongoClient] = None


def shared_client() -> MongoClient:
    """Return the process-wide ``MongoClient`` singleton. Lazy."""
    global _client
    if _client is None:
        if not _MONGO_URL:
            raise RuntimeError(
                "MONGO_URL is not configured — set it in /app/backend/.env "
                "or export it before running pytest.")
        _client = MongoClient(_MONGO_URL)
    return _client


def shared_db() -> Database:
    """Return the process-wide ``Database`` singleton. Lazy."""
    if not _DB_NAME:
        raise RuntimeError(
            "DB_NAME is not configured — set it in /app/backend/.env "
            "or export it before running pytest.")
    return shared_client()[_DB_NAME]
