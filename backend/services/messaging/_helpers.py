"""Phase I1.7.b · Feb-2026 — Shared helpers for tenant messaging providers.

Providers store their configuration as a JSON string inside the
encrypted blob (via ``services.secrets.put_secret``). This module
centralises:

* JSON serialisation of the config dict on the way in
* JSON deserialisation on the way out
* Required-field validation with error messages that NEVER echo the
  provided values
* ``test-mode`` short-circuit env checks so tests can exercise send
  flows without an outbound HTTP call.

Every provider imports from here so the shape stays consistent.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.secrets import get_secret, put_secret
from services.secrets.models import ConnectionType

from .models import InvalidProviderConfig


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sms_testmode_mock() -> bool:
    return os.environ.get("SMS_TESTMODE_MOCK", "").strip().lower() in ("1", "true", "yes")


def email_testmode_mock() -> bool:
    return os.environ.get("EMAIL_TESTMODE_MOCK", "").strip().lower() in ("1", "true", "yes")


def fallback_enabled() -> bool:
    """Platform messaging fallback default = ON during the migration
    window. Flip ``MESSAGING_PLATFORM_FALLBACK_ENABLED=false`` to
    force every send through a tenant-owned provider."""
    return os.environ.get("MESSAGING_PLATFORM_FALLBACK_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def validate_config(
    *, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
) -> None:
    """Raise ``InvalidProviderConfig`` if a required field is missing
    or blank. Error message names the field but NEVER echoes any
    provided value (safety net for accidental log leakage).
    """
    missing: List[str] = []
    for name, meta in schema.items():
        if not meta.get("required"):
            continue
        val = config.get(name)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(name)
    if missing:
        raise InvalidProviderConfig(
            f"provider={provider_key} missing required fields: {', '.join(missing)}"
        )


async def save_provider_config(
    *, tenant_id: str, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
    public_account_id: Optional[str] = None,
    primary_secret_field: Optional[str] = None,
    db=None,
) -> None:
    """Validate + JSON-serialise + encrypt-at-rest the config.

    ``config`` MAY contain both secret and public fields — we don't
    split them here because everything ends up encrypted anyway; the
    public identifier stored in ``connected_account_id`` is what the
    UI displays post-connection.

    ``primary_secret_field`` names the field whose value drives the
    ``last_4`` display mask (I1.7.b.fix). Should reference a
    ``secret=True`` field. If unset, ``last_4`` in the UI is
    computed off the JSON-blob tail (previous behaviour) which
    yields garbage like ``"}"`` — callers SHOULD supply this.
    """
    validate_config(provider_key=provider_key, config=config, schema=schema)
    # Compact JSON to keep ciphertext small — sort keys so a rotated
    # write with the same values is bit-for-bit identical (helpful
    # for debugging encryption-boundary drift).
    plaintext = json.dumps(config, sort_keys=True, separators=(",", ":"))
    # Resolve the mask source from the raw config dict — NOT the
    # serialized plaintext — so the last-4 chars are meaningful even
    # after JSON escaping.
    mask_source: Optional[str] = None
    if primary_secret_field and primary_secret_field in config:
        raw = config.get(primary_secret_field)
        if isinstance(raw, str) and raw:
            mask_source = raw
    await put_secret(
        tenant_id, provider_key, plaintext,
        connection_type=ConnectionType.API_KEY,
        connected_account_id=public_account_id,
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
        # Legacy rows written by an earlier phase stored the raw api
        # key as a bare string; wrap into the dict shape so callers
        # never need to switch on the payload type.
        return {"api_key": pt}
