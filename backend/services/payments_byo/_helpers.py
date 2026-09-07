"""Phase I1.7.d · Feb-2026 — Shared helpers for Payments-BYO providers.

JSON-encode the config into the encrypted blob (via ``services.secrets.put_secret``)
and provide a test-mode short-circuit + HMAC verification helper.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.secrets import get_secret, put_secret
from services.secrets.models import ConnectionType

from .models import InvalidPaymentsProviderConfig


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def payments_testmode_mock() -> bool:
    return os.environ.get("PAYMENTS_TESTMODE_MOCK", "").strip().lower() in ("1", "true", "yes")


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
        raise InvalidPaymentsProviderConfig(
            f"provider={provider_key} missing required fields: {', '.join(missing)}"
        )


async def save_provider_config(
    *, tenant_id: str, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
    primary_secret_field: Optional[str] = None,
    db=None,
) -> None:
    """Validate + JSON-serialise + encrypt-at-rest the payments provider
    config. Same shape as the AI/Maps ``save_provider_config`` — keeps
    the preserve-secret / cap-only-edit uniform across families.
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


def hmac_sha256_hex(*, secret: str, payload: bytes) -> str:
    """HMAC-SHA256(payload) hex-digest with the tenant's webhook secret."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def hmac_sha512_hex(*, secret: str, payload: bytes) -> str:
    """HMAC-SHA512(payload) hex-digest — Authorize.Net's convention."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha512).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").strip().lower(), (b or "").strip().lower())
