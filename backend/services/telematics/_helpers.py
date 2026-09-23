"""Phase P39 · Feb-2026 — Shared helpers for Telematics BYO providers.

Mirrors ``services.maps._helpers`` — JSON-encodes the config into the
encrypted blob (via ``services.secrets.put_secret``) and provides a
matching ``load_provider_config`` for read-back.

Encryption:
  * All fields (secret + non-secret) are serialised together into a
    single JSON string, which is then AES-256-GCM encrypted at rest
    via ``put_secret``.  See ``services.secrets.crypto`` for the
    key hierarchy.
  * ``primary_secret_field`` is passed through so the row's ``last_4``
    display field is derived from the api_key (never the account_id).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.secrets import get_secret, put_secret
from services.secrets.models import ConnectionType

from .models import InvalidTelematicsProviderConfig


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_config(
    *, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
) -> None:
    """Raise ``InvalidTelematicsProviderConfig`` if any required
    field in ``schema`` is missing / blank in ``config``.  Mirrors
    ``services.maps._helpers.validate_config``.
    """
    missing: List[str] = []
    for name, meta in schema.items():
        if not meta.get("required"):
            continue
        val = config.get(name)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(name)
    if missing:
        raise InvalidTelematicsProviderConfig(
            f"provider={provider_key} missing required fields: "
            f"{', '.join(missing)}"
        )


async def save_provider_config(
    *, tenant_id: str, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
    primary_secret_field: Optional[str] = None,
    db=None,
) -> None:
    """Validate + JSON-serialise + encrypt-at-rest the Telematics
    provider config.  ``config`` MUST include ``api_key``,
    ``account_id``, and ``webhook_secret``; Geotab MAY include
    an optional ``server_url``.
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
    """Decrypt + JSON-parse the stored config.  Returns ``None`` if
    the tenant hasn't saved this provider yet.  If the stored value
    is a legacy plain string (predates the JSON-blob shape), it's
    treated as the api_key.
    """
    pt = await get_secret(tenant_id, provider_key, db=db)
    if not pt:
        return None
    try:
        return json.loads(pt)
    except Exception:
        return {"api_key": pt}
