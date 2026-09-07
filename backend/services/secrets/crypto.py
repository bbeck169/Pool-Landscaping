"""Phase I1.7.a · Feb-2026 — AES-256-GCM primitives + KEK wrapping.

Threat model
------------
Adversary with read access to the Mongo ``tenant_secrets`` collection
but NOT to the ``SECRETS_MASTER_KEY`` env var (or the future KMS-
managed KEK) must not be able to recover plaintext secrets.

Design
------
* Every record gets a fresh 12-byte GCM IV. Nonce reuse under GCM
  is catastrophic — we generate via ``os.urandom`` at write time.
* Ciphertext is AES-256-GCM with a per-record IV. The auth tag is
  stored alongside so tampering is detected on read.
* **Key hierarchy**:
    - ``KEK`` (key-encryption key): the master key. In *local /dev*
      it is a base64-encoded 32-byte value in ``SECRETS_MASTER_KEY``.
      In *production* the same env var must be materialized from a
      KMS unwrap call (AWS KMS ``Decrypt`` or GCP KMS ``decrypt``),
      NOT stored in plaintext on disk. That swap is a caller-side
      concern — this module only sees the resolved 32 bytes.
    - ``DEK`` (data-encryption key): a fresh 32-byte value generated
      per record and wrapped by the KEK using AES-256-GCM. The
      wrapped DEK is persisted alongside the ciphertext. If the
      DEK were ever compromised, only that single record is at
      risk.
    - **Fast path (single-tenant / dev)**: to avoid per-record DEK
      generation overhead we allow a "direct KEK" mode when the
      ``SECRETS_DIRECT_KEK`` env is truthy — the record's IV is
      still fresh, but the record is encrypted directly with the
      KEK and ``dek_wrapped`` is ``None``. Default: enabled for
      dev, disabled for prod (set ``SECRETS_DIRECT_KEK=0`` in
      prod once KMS is wired).

**Nothing in this module ever logs plaintext.** ``encrypt`` and
``decrypt`` operate on ``bytes`` and raise on any tamper / bad-tag
so callers must catch ``InvalidTag`` at the boundary.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ── Errors ───────────────────────────────────────────────────────
class SecretCryptoError(Exception):
    """Base error for all crypto misuse (missing KEK, bad ciphertext)."""


class MasterKeyUnavailable(SecretCryptoError):
    """``SECRETS_MASTER_KEY`` env var is missing or malformed."""


# ── KEK resolution ───────────────────────────────────────────────
def _resolve_kek() -> bytes:
    raw = os.environ.get("SECRETS_MASTER_KEY", "").strip()
    if not raw:
        raise MasterKeyUnavailable(
            "SECRETS_MASTER_KEY env var is not set — refusing to "
            "encrypt / decrypt tenant secrets. In dev, generate one "
            "with `python -c \"import secrets, base64; "
            "print(base64.b64encode(secrets.token_bytes(32)).decode())\"` "
            "and add it to backend/.env."
        )
    try:
        kek = base64.b64decode(raw)
    except Exception as e:
        raise MasterKeyUnavailable(
            f"SECRETS_MASTER_KEY is not valid base64: {e}"
        )
    if len(kek) != 32:
        raise MasterKeyUnavailable(
            f"SECRETS_MASTER_KEY must decode to 32 bytes; got "
            f"{len(kek)}."
        )
    return kek


def _direct_kek_mode() -> bool:
    return os.environ.get("SECRETS_DIRECT_KEK", "1").strip() not in ("0", "false", "no", "")


# ── Public dataclass ─────────────────────────────────────────────
@dataclass
class EncryptedRecord:
    """The three bytestrings a record needs to be re-decrypted.

    All fields are **base64 strings** so they can be stored in Mongo
    as safe JSON scalars.
    """
    encrypted_blob: str
    iv: str
    auth_tag: str
    dek_wrapped: Optional[str] = None


# ── Encrypt / decrypt ────────────────────────────────────────────
def encrypt(plaintext: str) -> EncryptedRecord:
    """Encrypt ``plaintext`` with either the direct-KEK path or a
    fresh wrapped DEK, and return the three base64 blobs the caller
    persists into the ``tenant_secrets`` row.

    Never logs, prints, or returns any component of ``plaintext``.
    """
    if not isinstance(plaintext, str):
        raise SecretCryptoError("plaintext must be a str")
    pt_bytes = plaintext.encode("utf-8")
    kek = _resolve_kek()

    if _direct_kek_mode():
        iv = os.urandom(12)
        # AESGCM.encrypt returns ciphertext + tag concatenated.
        combined = AESGCM(kek).encrypt(iv, pt_bytes, associated_data=None)
        ct, tag = combined[:-16], combined[-16:]
        return EncryptedRecord(
            encrypted_blob=base64.b64encode(ct).decode(),
            iv=base64.b64encode(iv).decode(),
            auth_tag=base64.b64encode(tag).decode(),
            dek_wrapped=None,
        )
    # Wrapped-DEK path
    dek = os.urandom(32)
    dek_iv = os.urandom(12)
    wrapped_combined = AESGCM(kek).encrypt(dek_iv, dek, associated_data=None)
    # We concatenate dek_iv + wrapped as the persisted wrapped-DEK
    # so unwrap can split it back out.
    dek_wrapped = base64.b64encode(dek_iv + wrapped_combined).decode()

    iv = os.urandom(12)
    combined = AESGCM(dek).encrypt(iv, pt_bytes, associated_data=None)
    ct, tag = combined[:-16], combined[-16:]
    return EncryptedRecord(
        encrypted_blob=base64.b64encode(ct).decode(),
        iv=base64.b64encode(iv).decode(),
        auth_tag=base64.b64encode(tag).decode(),
        dek_wrapped=dek_wrapped,
    )


def decrypt(record: EncryptedRecord) -> str:
    """Decrypt the record and return plaintext. Raises on tamper.

    Callers should catch ``cryptography.exceptions.InvalidTag`` and
    surface a generic "secret unreadable" error — never echo the
    exception message to the client.
    """
    kek = _resolve_kek()
    ct = base64.b64decode(record.encrypted_blob)
    iv = base64.b64decode(record.iv)
    tag = base64.b64decode(record.auth_tag)
    combined = ct + tag

    if record.dek_wrapped:
        wrapped_bytes = base64.b64decode(record.dek_wrapped)
        dek_iv, wrapped_combined = wrapped_bytes[:12], wrapped_bytes[12:]
        try:
            dek = AESGCM(kek).decrypt(dek_iv, wrapped_combined, associated_data=None)
        except InvalidTag as e:
            raise SecretCryptoError("DEK unwrap failed (bad KEK or tampered record)") from e
        try:
            pt_bytes = AESGCM(dek).decrypt(iv, combined, associated_data=None)
        except InvalidTag as e:
            raise SecretCryptoError("Record decrypt failed (tampered ciphertext)") from e
        return pt_bytes.decode("utf-8")

    try:
        pt_bytes = AESGCM(kek).decrypt(iv, combined, associated_data=None)
    except InvalidTag as e:
        raise SecretCryptoError("Record decrypt failed (bad KEK or tampered ciphertext)") from e
    return pt_bytes.decode("utf-8")


def last_4(plaintext: str) -> str:
    """Safe-to-persist last-4-of-plaintext helper. Never returns a
    slice of the *key material* — for OAuth access tokens (which are
    long random blobs) the last 4 chars are safe to display; for
    api keys the same holds by convention (Stripe, Twilio, etc. all
    have keys ≥ 32 chars)."""
    if not plaintext or len(plaintext) < 4:
        return ""
    return plaintext[-4:]
