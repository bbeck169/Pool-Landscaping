"""Phase I1.7.c.2 · Feb-2026 — Shared helpers for Maps BYO providers.

Mirrors ``services.ai._helpers`` and ``services.messaging._helpers``.
JSON-encodes the config into the encrypted blob (via
``services.secrets.put_secret``) and provides a test-mode
short-circuit for unit tests.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.secrets import get_secret, put_secret
from services.secrets.models import ConnectionType

from .models import InvalidMapsProviderConfig


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def maps_testmode_mock() -> bool:
    return os.environ.get("MAPS_TESTMODE_MOCK", "").strip().lower() in ("1", "true", "yes")


def validate_config(
    *, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
) -> None:
    missing: List[str] = []
    for name, meta in schema.items():
        if not meta.get("required"):
            continue
        val = config.get(name)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(name)
    if missing:
        raise InvalidMapsProviderConfig(
            f"provider={provider_key} missing required fields: {', '.join(missing)}"
        )


async def save_provider_config(
    *, tenant_id: str, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
    primary_secret_field: Optional[str] = None,
    db=None,
) -> None:
    """Validate + JSON-serialise + encrypt-at-rest the Maps provider
    config. ``config`` must include ``api_key`` (secret) and MAY
    include provider-specific fields (``region_bias``, ``style``,
    etc.).
    """
    validate_config(provider_key=provider_key, config=config, schema=schema)
    plaintext = json.dumps(config, sort_keys=True, separators=(",", ":"))
    mask_source: Optional[str] = None
    if primary_secret_field and primary_secret_field in config:
        raw = config.get(primary_secret_field)
        if isinstance(raw, str) and raw:
            mask_source = raw
    await put_secret(
        tenant_id, provider_key, plaintext,
        connection_type=ConnectionType.API_KEY,
        connected_account_id=None,
        mask_source=mask_source,
        db=db,
    )


async def load_provider_config(
    *, tenant_id: str, provider_key: str, db=None,
) -> Optional[Dict[str, Any]]:
    pt = await get_secret(tenant_id, provider_key, db=db)
    if not pt:
        return None
    try:
        return json.loads(pt)
    except Exception:
        return {"api_key": pt}


def current_period_yyyymm() -> str:
    d = datetime.now(timezone.utc)
    return f"{d.year:04d}{d.month:02d}"
