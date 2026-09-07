"""Phase I1.7.c.1 · Feb-2026 — Shared helpers for AI BYO providers.

Mirrors ``services.messaging._helpers`` — JSON-encode the config into
the encrypted blob (via ``services.secrets.put_secret``) and provide
a test-mode short-circuit so unit tests exercise the adapter code
paths without any outbound HTTP.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.secrets import get_secret, put_secret
from services.secrets.models import ConnectionType

from .models import InvalidAIProviderConfig


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ai_testmode_mock() -> bool:
    return os.environ.get("AI_TESTMODE_MOCK", "").strip().lower() in ("1", "true", "yes")


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
        raise InvalidAIProviderConfig(
            f"provider={provider_key} missing required fields: {', '.join(missing)}"
        )


async def save_provider_config(
    *, tenant_id: str, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
    primary_secret_field: Optional[str] = None,
    db=None,
) -> None:
    """Validate + JSON-serialise + encrypt-at-rest the AI provider
    config. ``config`` must include ``api_key`` (secret) and MAY
    include ``default_model``. ``primary_secret_field`` should
    reference the ``secret=True`` field whose value drives ``last_4``.
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
    """Return the tenant's decrypted config dict, or ``None`` if no
    row exists. Callers MUST treat the return value as short-lived
    plaintext and NEVER log or return it upstream."""
    pt = await get_secret(tenant_id, provider_key, db=db)
    if not pt:
        return None
    try:
        return json.loads(pt)
    except Exception:
        # Legacy rows written as bare strings.
        return {"api_key": pt}


def current_period_yyyymm() -> str:
    d = datetime.now(timezone.utc)
    return f"{d.year:04d}{d.month:02d}"
