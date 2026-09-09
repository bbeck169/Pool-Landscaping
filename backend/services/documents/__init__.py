"""Feb-2026 · Editable Sent Docs · Phase 1 — documents service package.

Re-export the version-history helpers so callers can
``from services.documents import snapshot_before_mutation``.
"""
from .versions import (
    snapshot_before_mutation,
    invalidate_signature_if_present,
    has_signature,
    normalize_doc_type,
    CANONICAL_DOC_TYPES,
)

__all__ = [
    "snapshot_before_mutation",
    "invalidate_signature_if_present",
    "has_signature",
    "normalize_doc_type",
    "CANONICAL_DOC_TYPES",
]
