"""Preview isolation · Feb-2026 P0.

Deliberately-tight boundary layer that guarantees real customer PII
never persists on the preview environment, regardless of ingress
path (admin JSON create, CSV import, PDF-invoice import, public lead
form, webhook, portal self-service).

Public API — import the names below, don't reach into submodules:

    from services.preview_isolation import (
        is_preview_env,              # True iff APP_ENV != "production"
        sanitize_pii_payload,        # deep dict/list sanitizer
        sanitize_csv_rows,           # CSV-row list sanitizer
        redact_free_text,            # notes/custom_fields redactor
        synthetic_bucket,            # deterministic hash → bucket int
        PREVIEW_SYNTHETIC_SALT,      # salt from env, immutable
        PIIIngressRejected,          # 400 raised on live-PM / SSN / DOB / CC / DL
        PreviewMiddleware,           # ASGI middleware (JSON body routes)
        PII_INGRESS_REGISTRY,        # declared ingress routes
        audit_route_registry,        # boot-time assertion result
    )

Rationale is captured in ``/app/memory/preview_data_leak_rca.md``.
"""
from .config import (
    is_preview_env,
    is_production_env,
    PREVIEW_SYNTHETIC_SALT,
    PREVIEW_TENANT_WHITELIST,
)
from .synthesizer import synthetic_bucket, synthesize_customer_fields
from .redactor import redact_free_text
from .decorator import (
    PIIIngressRejected,
    sanitize_pii_payload,
    sanitize_csv_rows,
    sanitize_pdf_extracted_rows,
)
from .middleware import PreviewMiddleware
from .registry import (
    PII_INGRESS_REGISTRY,
    audit_route_registry,
    assert_registry_coverage,
)

__all__ = [
    "is_preview_env",
    "is_production_env",
    "PREVIEW_SYNTHETIC_SALT",
    "PREVIEW_TENANT_WHITELIST",
    "synthetic_bucket",
    "synthesize_customer_fields",
    "redact_free_text",
    "PIIIngressRejected",
    "sanitize_pii_payload",
    "sanitize_csv_rows",
    "sanitize_pdf_extracted_rows",
    "PreviewMiddleware",
    "PII_INGRESS_REGISTRY",
    "audit_route_registry",
    "assert_registry_coverage",
]
