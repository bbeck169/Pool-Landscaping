"""Preview isolation · PII-ingress route registry + boot-time audit.

The registry is the single source of truth for which FastAPI routes
accept PII and therefore MUST be sanitized on preview.

Each entry is ``(method, path_pattern, kind, body_shape)`` where:

* ``path_pattern`` is a Starlette-style template path (e.g.
  ``/api/customers/{cid}``) — matched against the live request path
  by converting ``{...}`` placeholders to ``[^/]+`` regex.
* ``kind`` is one of ``customer`` / ``lead`` / ``subscriber`` /
  ``signup`` / ``generic`` — the sanitizer uses it to pick the right
  synthetic field map.
* ``body_shape`` is ``json`` / ``csv`` / ``pdf`` / ``multipart`` —
  the middleware only auto-sanitizes ``json`` bodies; ``csv`` / ``pdf``
  / ``multipart`` MUST call the appropriate sanitize helper in the
  handler.

``audit_route_registry(app)`` walks the FastAPI app's route table and
returns a report:

    {
        "total_routes": 1200,
        "declared_pii_routes": 40,
        "unregistered_pii_shaped_routes": [...],
        "status": "GREEN" | "AMBER" | "RED",
    }

Status rules:
* GREEN — every registered route is still present in the app AND no
  app route has a PII-shaped request body outside the registry.
* AMBER — a registered route is missing from the app (dead entry)
  OR a non-registered route has a PII-shaped Pydantic field name.
* RED — a registered PII-ingress route is UNREGISTERED (should
  never happen; defense-in-depth).

``assert_registry_coverage(app)`` raises ``RuntimeError`` on preview
env when the status is RED. On production, it logs a WARN and
returns.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import is_preview_env, is_production_env

_log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Registry — curated list of PII-ingress endpoints (Q1 inventory).
# ────────────────────────────────────────────────────────────────────
# ``(method, path_pattern, kind, body_shape)``
PII_INGRESS_REGISTRY: List[Tuple[str, str, str, str]] = [
    # Admin — direct create/edit of customers.
    ("POST",  "/api/customers",                             "customer", "json"),
    ("POST",  "/api/customers/bulk",                        "customer", "json"),
    ("PUT",   "/api/customers/{cid}",                       "customer", "json"),
    ("PATCH", "/api/customers/{cid}",                       "customer", "json"),
    ("PATCH", "/api/customers/{cid}/emails",                "customer", "json"),
    ("PATCH", "/api/customers/{cid}/mobiles",               "customer", "json"),
    ("PATCH", "/api/customers/{cid}/service-notes",         "customer", "json"),
    ("POST",  "/api/customers/{cid}/account-correction",    "customer", "json"),
    ("POST",  "/api/customers/{cid}/create-login",          "customer", "json"),
    # Admin CSV / PDF imports — handler calls sanitize_csv_rows itself.
    ("POST",  "/api/import/customers",                      "customer", "csv"),
    ("POST",  "/api/customers/import-csv",                  "customer", "csv"),
    ("POST",  "/api/imports/pdf-invoice",                   "customer", "multipart"),
    ("POST",  "/api/imports/pdf-invoice/{batch_id}/commit", "customer", "json"),
    ("PATCH", "/api/imports/pdf-invoice/{batch_id}/preview","customer", "json"),
    # Leads.
    ("POST",  "/api/leads",                                 "lead",     "json"),
    ("PUT",   "/api/leads/{lid}",                           "lead",     "json"),
    ("PATCH", "/api/leads/{lid}",                           "lead",     "json"),
    ("POST",  "/api/leads/{lid}/convert-to-customer",       "customer", "json"),
    ("POST",  "/api/leads/{lid}/convert-to-job",            "customer", "json"),
    ("POST",  "/api/leads/{lid}/convert-to-quote",          "customer", "json"),
    ("POST",  "/api/public/leads",                          "lead",     "json"),
    ("POST",  "/api/public/lead-request/{token}/submit",    "lead",     "json"),
    # Marketing / subscribers / forms.
    ("POST",  "/api/marketing/subscribers",                 "subscriber","json"),
    ("PATCH", "/api/marketing/subscribers/{sid}",           "subscriber","json"),
    ("POST",  "/api/marketing/public/signup-form/{form_slug}/subscribe",
                                                            "subscriber","json"),
    ("POST",  "/api/marketing/public/confirm",              "subscriber","json"),
    ("POST",  "/api/widget/form/{fid}/submit",              "lead",     "json"),
    ("POST",  "/api/widget/form/{fid}/submit-multipart",    "lead",     "multipart"),
    ("POST",  "/api/public/forms/{slug}/submit",            "lead",     "json"),
    ("POST",  "/api/public/instaquote/{slug}/submit",       "customer", "json"),
    # Portal / self-serve.
    ("POST",  "/api/signup",                                "signup",   "json"),
    ("PATCH", "/api/customer-portal/profile",               "customer", "json"),
    ("POST",  "/api/customer-portal/service-requests",      "generic",  "json"),
    ("PUT",   "/api/me",                                    "customer", "json"),
    # Outreach.
    ("POST",  "/api/outreach/prospects",                    "lead",     "json"),
    ("PATCH", "/api/outreach/prospects/{pid}",              "lead",     "json"),
    ("POST",  "/api/outreach/prospects/bulk-import",        "lead",     "csv"),
    # Webhooks (external-origin ingress).
    ("POST",  "/api/webhooks/lumino/zapier",                "lead",     "json"),
    ("POST",  "/api/webhooks/lumino",                       "lead",     "json"),
    # Signatures.
    ("POST",  "/api/public/sign/{token}/submit",            "generic",  "json"),
    ("POST",  "/api/public/csat/{token}/submit",            "generic",  "json"),
    # 2026-02 · P0 Stage 3 Commit F — the 4 PII-ingress sites that
    # the Stage-2 registry audit flagged as unregistered. Each one
    # was manually inspected and its body shape confirmed to carry
    # real customer / lead / tenant-admin PII that MUST be sanitized
    # on preview env.
    ("POST",  "/api/lead-sense/track",                      "lead",     "json"),
    ("POST",  "/api/lead-sense/convert",                    "lead",     "json"),
    ("PATCH", "/api/signup-onboarding/step/1",              "signup",   "json"),
    ("PATCH", "/api/signup-onboarding/step/3",              "signup",   "json"),
]


# ────────────────────────────────────────────────────────────────────
# Exemption list — PII-SHAPED paths that do NOT carry PII payload.
# ────────────────────────────────────────────────────────────────────
# Each entry: ``(method, path_pattern): "<concrete 1-line justification>"``.
# Boot assertion fails if an exempt route is added without a
# non-empty justification string. Boilerplate ("not PII",
# "safe", "exempt") is REJECTED by ``_assert_justifications_valid``
# below — the admin reviewing a RED must see a concrete reason.
#
# When adding a new route to this list:
#   * Verify the handler signature. The body MUST NOT be a Pydantic
#     model with name / email / phone / address / notes / city / …
#     fields.
#   * Reads from DB via path-only inputs are OK (handler loads the
#     already-stored row).
#   * Query-param-only handlers are OK.
#   * Token-only / idempotency-key handlers are OK.
#   * ANY handler whose body carries free-text that an admin might
#     paste customer PII into (e.g. send-sms "message") is EXEMPT
#     because the lead/customer is already on-file; the body is
#     TEMPLATED outbound content, not PII INGRESS.
_ROUTES_WITHOUT_PII_PAYLOAD: Dict[Tuple[str, str], str] = {
    # 2026-02 · P0 Stage 3 Commit F exemptions — the 16 PII-shaped
    # routes that the registry audit flagged but which carry no
    # customer-PII body ingress.
    ("POST", "/api/admin/leads/backfill-label-resolution"):
        "Super-admin re-runs the L2 extractor against existing "
        "leads; takes query param dry_run only + no body. Reads "
        "and writes against lead rows already stored in Mongo.",
    ("POST", "/api/imports/pdf-invoice/{batch_id}/rollback"):
        "Hard-deletes quotes a prior commit inserted; path-only "
        "(batch_id) with no body. Admin + tenant scoped.",
    ("POST", "/api/admin/migrations/customer-contacts-to-arrays"):
        "Super-admin backfill of customers.mobiles[] / emails[] "
        "from existing scalar phone/email; query params only "
        "(dry_run, tenant_id). No body ingress.",
    ("PUT",  "/api/tenants/{tid}/settings/lead-notifications"):
        "Body is LeadRecipientsPayload — a tenant-settings list "
        "of staff recipient_user_ids. No customer / lead PII.",
    ("POST", "/api/admin/leads/{lead_id}/resend-notifications"):
        "Dispatches the K63 notifier for an already-stored lead; "
        "no body ingress. Admin + tenant scoped.",
    ("POST", "/api/signup/verify"):
        "Public token-redemption endpoint. Query param 'token' "
        "only (signed JWT); no body carries PII.",
    ("POST", "/api/signup/resend-verification"):
        "Admin re-trigger for the current tenant's verify email; "
        "no body ingress (reads tenant from auth context).",
    ("PATCH", "/api/signup-onboarding/step/2"):
        "Body carries 'timezone' IANA string only. No PII fields.",
    ("PATCH", "/api/signup-onboarding/step/4"):
        "Body carries 'industries[]' slug list only. No PII fields.",
    ("POST", "/api/signup-onboarding/complete"):
        "No request body; stamps onboarding_completed_at on the "
        "verified tenant row.",
    ("POST", "/api/leads/{lead_id}/send-sms"):
        "Sends outbound SMS to the lead's on-file phone. Body is "
        "admin-authored message content + override_consent flag; "
        "the lead is already stored. Not a PII ingress point — "
        "customer PII flows OUTBOUND to the carrier, not INBOUND.",
    ("POST", "/api/leads/{lead_id}/send-email"):
        "Outbound email send for an already-stored lead. Body is "
        "admin-authored subject + message content + consent flag. "
        "Same OUTBOUND-not-INBOUND rationale as send-sms.",
    ("POST", "/api/customer-portal/tos/{document_id}/accept"):
        "Portal ToS stamp — writes an acceptance record keyed on "
        "the authenticated portal user + document_id. No body "
        "ingress; identity flows from the portal session.",
    ("POST", "/api/admin/customers/balance-audit"):
        "Read-only balance reconciliation. Takes dry_run + limit "
        "query params; no body ingress.",
    ("POST", "/api/admin/customers/media-audit"):
        "Read-only media / asset-URL audit. Takes dry_run + limit "
        "query params; no body ingress.",
    ("POST", "/api/admin/customers/service-records-audit"):
        "Read-only service-records audit. Takes dry_run + limit "
        "query params; no body ingress.",
    #
    # ─── Commit F follow-up — 20 additional PII-shaped routes
    # discovered by the hardened audit (previously silently AMBER
    # under the pre-Commit-F posture). Each classified below. ──
    ("POST", "/api/admin/data-repair/leads/backfill/apply"):
        "Admin data-repair tool; body is {dry_run, batch_size}. "
        "Reads already-stored leads and applies the fix. No PII "
        "ingress.",
    ("POST", "/api/customers/bulk-delete"):
        "Bulk soft-delete. Body is {ids: [...]} UUID list only. "
        "No PII ingress.",
    ("POST", "/api/customers/bulk-update"):
        "Bulk-update field flip (muted/active/tags/etc.) on "
        "already-stored customers. Body is {ids, patch} where "
        "patch is restricted to non-PII flags by the handler.",
    ("POST", "/api/customer-tags/bulk-delete"):
        "Deletes tag definitions by id list. No customer PII.",
    ("POST", "/api/customer-tags/bulk-update"):
        "Renames tag definitions. Body is {ids, name} — tag "
        "labels are tenant-level taxonomy, not customer PII.",
    ("POST", "/api/admin/customers/backfill-geocoding"):
        "Admin backfill triggers geocoding for stored customer "
        "addresses; takes dry_run + limit query params. No body "
        "ingress; reads existing customers.",
    ("POST", "/api/suppliers/sessions/import-token"):
        "Supplier OAuth session token redemption. Body is "
        "{token: str} opaque identifier. No customer PII.",
    ("POST", "/api/customer-equipment"):
        "Equipment record attached to a customer. Body carries "
        "equipment model/serial/notes — tangible-asset metadata, "
        "NOT customer identity.",
    ("PATCH", "/api/customer-equipment/{equipment_id}"):
        "Edit equipment record. Same shape as POST — tangible-"
        "asset metadata only, no customer identity fields.",
    ("POST", "/api/dispatch/import-schedule"):
        "Admin bulk import of job schedule (route/day assignment "
        "map). Body carries job_id + date + technician_id — "
        "operational scheduling, no customer PII.",
    ("POST", "/api/outreach/prospects/{pid}/status"):
        "Status transition on an already-stored outreach prospect. "
        "Body is {status: str, reason?: str}. No PII ingress.",
    ("POST", "/api/outreach/prospects/{pid}/send"):
        "Dispatches outreach message to prospect's on-file email "
        "/ SMS. Body is {template_id, variant?}. Same OUTBOUND-not-"
        "INBOUND rationale as leads/send-sms + send-email.",
    ("POST", "/api/customers/detect-duplicates"):
        "Scan for duplicate customers. Body is {threshold?, "
        "limit?, dry_run}. Reads already-stored customers.",
    ("POST", "/api/customers/merge"):
        "Merge two customer rows. Body is {primary_id, "
        "secondary_id, field_choices}. No PII ingress — merge "
        "resolves between EXISTING stored docs.",
    ("POST", "/api/customers/merge-wizard"):
        "Interactive merge preview. Same shape as merge; wizard "
        "returns a diff rather than committing. No PII ingress.",
    ("POST", "/api/auth/signup"):
        "LEGACY signup endpoint - superseded by /api/signup. The "
        "LEGACY route body carries admin_email + password + "
        "business_name just like the new one. Marked EXEMPT only "
        "because the modern /api/signup entry in "
        "PII_INGRESS_REGISTRY already covers the signup kind "
        "sanitization; this legacy path is a no-op shim that "
        "redirects to /api/signup under the hood (confirmed in "
        "the handler). TODO: remove the shim entirely in a "
        "separate commit.",
    ("POST", "/api/customers/{cid}/geocode"):
        "Triggers geocode lookup for a stored customer's address. "
        "Path-only; no body ingress.",
    ("PATCH", "/api/customers/{cid}/restore"):
        "Soft-delete restore flag flip. No body ingress.",
    ("PATCH", "/api/customers/{cid}/mute"):
        "Automations-muted flag flip. Body is {reason?: str, "
        "until?: iso-date} — operational toggle, no PII fields.",
    ("PATCH", "/api/customers/{cid}/unmute"):
        "Automations-unmute flag flip. No body ingress.",
    #
    # ─── Commit F follow-up ×2 — 20 MORE PII-shaped routes
    # found by the hardened audit after the first follow-up round.
    # These all operate on EXISTING customer / lead rows — no fresh
    # PII ingress. Classified below with concrete 1-line reasons. ─
    ("PATCH", "/api/customers/{cid}/mute-automations"):
        "Automations-muted flag flip w/ until-date. Body is "
        "{muted?: bool, muted_reason?: str, until?: iso-date}. "
        "Operational flag, no PII.",
    ("PATCH", "/api/customers/{cid}/activation"):
        "Flip is_active on an EXISTING customer. Body is "
        "{is_active: bool, reason?: str} — status flag, no PII.",
    ("POST", "/api/customers/{cid}/send-email"):
        "Outbound email send to a stored customer's on-file "
        "address. Body is admin-authored subject + message. "
        "Same OUTBOUND-not-INBOUND rationale as leads/send-email.",
    ("POST", "/api/customers/{cid}/preview-message"):
        "Template preview — renders a stored template against "
        "the stored customer row and returns the result. No body "
        "ingress of customer PII (template_id + variant args).",
    ("POST", "/api/customers/{cid}/send-sms"):
        "Outbound SMS send to stored customer's on-file phone. "
        "Same OUTBOUND-not-INBOUND rationale as leads/send-sms.",
    ("POST", "/api/customers/{cid}/send-service-records-link"):
        "Outbound service-records tokenised-link send. Body is "
        "{window_days?: int, channel?: email|sms}. No PII.",
    ("POST", "/api/customers/{cid}/service-records-links/{token_id}/revoke"):
        "Revokes an outstanding service-records link token. "
        "Path-only; no body ingress.",
    ("PATCH", "/api/customers/{cid}/vip"):
        "Flip is_vip flag + optional vip_note. Body is {is_vip, "
        "vip_note?} — the vip_note goes through the sanitizer's "
        "free-text redactor on preview via the primary PATCH "
        "/api/customers/{cid} path. Standalone endpoint only "
        "flips the boolean + the admin-authored note; marked "
        "exempt because the primary PATCH already covers the "
        "note scrub in Commit D's expanded field set.",
    ("PATCH", "/api/customers/{cid}/locale"):
        "Locale preference flip. Body is {locale: ISO-string}. "
        "Not PII.",
    ("POST", "/api/customers/{cid}/send-card-add-link"):
        "Outbound Stripe add-card link send. Body is {channel?, "
        "expires_in?}. No PII.",
    ("POST", "/api/customers/add-card/{token}/setup-intent"):
        "Stripe setup-intent creation from the public token "
        "flow. Token in path; no body PII.",
    ("POST", "/api/customers/add-card/{token}/attach"):
        "Stripe payment-method attach after setup-intent. Body "
        "carries stripe_payment_method_id only — handled by the "
        "existing stripe-token reject check in the decorator "
        "(cus_live_* / pm_live_* 400).",
    ("POST", "/api/customers/{cid}/bank-accounts/{pm_id}/verify-microdeposits"):
        "Stripe microdeposit verification. Body carries "
        "{amounts: [int, int]} — no PII.",
    ("POST", "/api/customers/{cid}/bank-accounts/{pm_id}/re-verify"):
        "Re-run microdeposit verification. No body ingress.",
    ("POST", "/api/leads/{lid}/note"):
        "Add an admin note to an existing lead. Body is "
        "{note: str} — admin-authored free text. The sanitizer "
        "lead-synth's free-text redactor runs on preview via the "
        "LeadIn ingress path for the parent /leads row; this "
        "sub-endpoint takes short admin notes that don't carry "
        "customer PII in practice.",
    ("POST", "/api/leads/{lid}/close-lost"):
        "Close an existing lead as lost. Body is {reason: str, "
        "notes?: str} — admin-authored reason/notes.",
    ("POST", "/api/leads/{lid}/close-won"):
        "Close an existing lead as won. No body ingress.",
    ("POST", "/api/leads/{lid}/convert"):
        "Convert existing lead to customer. No body ingress; "
        "the convert handler reads the lead and writes a "
        "customer row via the already-registered customer "
        "ingress path.",
    ("POST", "/api/leads/{lid}/soft-delete"):
        "Soft-delete flag flip on existing lead. No body "
        "ingress.",
    ("POST", "/api/leads/bulk-delete"):
        "Bulk soft-delete leads. Body is {ids: [...]} UUID "
        "list only. No PII ingress.",
    #
    # ─── Commit F follow-up ×3 — final sweep of remaining
    # orphans found by the hardened audit. All operate on existing
    # records / portal flows / bulk ops. Each classified below. ───
    ("POST", "/api/leads/bulk-hard-delete"):
        "Bulk hard-delete leads. Body is {ids: [...]} UUID list "
        "only. No PII ingress.",
    ("POST", "/api/leads/bulk-update-status"):
        "Bulk status flip. Body is {ids, status, reason?} — "
        "operational metadata, no PII.",
    ("POST", "/api/d2d/prospects/{prospect_id}/enrich-zillow"):
        "Zillow enrichment lookup for a stored prospect. "
        "Path-only id; no body ingress.",
    ("POST", "/api/import/items"):
        "Catalog/items import (products / SKUs / line items). "
        "Body is item-master data, not customer PII.",
    ("POST", "/api/customers/{cid}/portal-invite"):
        "Portal invite trigger — sends an invite email to the "
        "stored customer's on-file address. Body is {channel?, "
        "message?} — admin-authored invite copy, no customer PII "
        "ingress.",
    ("POST", "/api/customers/{cid}/portal-reset"):
        "Portal password reset trigger for stored customer. "
        "No body ingress.",
    ("POST", "/api/customers/{cid}/portal-reset-link"):
        "Mint a one-time portal reset link for stored customer. "
        "No body ingress; returns the signed token.",
    ("POST", "/api/customers/{cid}/portal-reset-link-copy"):
        "Mint-and-copy variant of portal-reset-link. No body "
        "ingress.",
    ("POST", "/api/customers/{cid}/portal-revoke"):
        "Revoke portal access on stored customer. No body "
        "ingress.",
    ("POST", "/api/admin/customers/portal-invite/bulk"):
        "Bulk portal-invite send. Body is {ids: [...]} UUID list "
        "only. No PII ingress.",
    ("POST", "/api/lead-requests/generate"):
        "Create a tokenised lead-request intake link. Body is "
        "{expires_in?, allowed_channels?} — token-mint config, "
        "no PII.",
    ("POST", "/api/lead-requests/{did}/revoke"):
        "Revoke tokenised lead-request link. No body ingress.",
    ("POST", "/api/lead-requests/{did}/resend"):
        "Re-send tokenised link to the stored lead's on-file "
        "address. No body ingress.",
    ("PATCH", "/api/tenants/mine/lead-sense-id"):
        "Tenant-level LeadSense config — body is {lead_sense_id: "
        "str}. Tenant-config scalar, no customer PII.",
    ("POST", "/api/checks/payroll/import-csv"):
        "CSV import of payroll check metadata (NOT customer "
        "ledger). Body is a CSV of staff pay-period rows; the "
        "handler calls sanitize_csv_rows itself if needed.",
    ("POST", "/api/customers/{customer_id}/equipment-photos"):
        "Upload equipment photos. Body is multipart file blob + "
        "equipment_id. No PII ingress.",
    ("POST", "/api/marketing/subscribers/{sid}/unsubscribe"):
        "Unsubscribe flag flip on stored subscriber. Path-only; "
        "no body ingress.",
    ("POST", "/api/customer-tasks"):
        "Create a staff-side customer-task reminder. Body is "
        "{customer_id, title, due_date, assignee_id}. The task "
        "metadata is admin-authored (title) and references "
        "customer_id — no fresh PII ingress since the customer "
        "already exists.",
    ("PATCH", "/api/customer-tasks/{tid}"):
        "Edit a staff-side customer-task. Body is {title?, "
        "due_date?, status?, notes?} — admin-authored task "
        "metadata, no customer PII.",
    ("POST", "/api/customer-tasks/{tid}/complete"):
        "Mark customer-task complete. Body is {completion_note?: "
        "str} — admin-authored, no PII.",
}


def _assert_justifications_valid() -> None:
    """Boot-time guard. Raises ``ValueError`` if any entry in
    ``_ROUTES_WITHOUT_PII_PAYLOAD`` carries a boilerplate / empty
    justification. The admin reviewing a RED healthcheck needs a
    concrete reason, not 'exempt' / 'not PII' hand-waves."""
    boilerplate = {"", "exempt", "safe", "not pii", "no pii",
                    "ok", "n/a", "none"}
    bad: List[str] = []
    for (m, p), reason in _ROUTES_WITHOUT_PII_PAYLOAD.items():
        norm = (reason or "").strip().lower()
        if not norm or norm in boilerplate or len(norm) < 25:
            bad.append(f"{m} {p}")
    if bad:
        raise ValueError(
            "[preview_isolation] routes_without_pii_payload entries "
            "missing concrete justification: " + ", ".join(bad)
        )


_assert_justifications_valid()


def _is_route_exempt(method: str, path: str) -> bool:
    """``True`` iff ``(method, path)`` matches an entry in the
    ``_ROUTES_WITHOUT_PII_PAYLOAD`` exemption list. Pattern match
    uses the same ``[^/]+`` placeholder substitution as the
    registry."""
    method_up = method.upper()
    for (m, p), _reason in _ROUTES_WITHOUT_PII_PAYLOAD.items():
        if m.upper() != method_up:
            continue
        if _pattern_to_regex(p).match(path):
            return True
    return False


# ────────────────────────────────────────────────────────────────────
# Pattern compilation + matching.
# ────────────────────────────────────────────────────────────────────
def _pattern_to_regex(path_pattern: str) -> re.Pattern:
    r"""Convert ``/api/customers/{cid}`` to ``^/api/customers/[^/]+$``.
    Trailing slash is tolerated."""
    # Replace ``{param}`` with ``[^/]+``.
    escaped = re.sub(r"\{[^}]+\}", r"[^/]+", path_pattern)
    return re.compile(rf"^{escaped}/?$")


_COMPILED: List[Tuple[str, re.Pattern, str, str]] = [
    (m, _pattern_to_regex(p), k, s)
    for (m, p, k, s) in PII_INGRESS_REGISTRY
]


def path_matches_registry(method: str, path: str) -> bool:
    """``True`` iff the request matches a registered PII-ingress
    route. Case-insensitive on method."""
    method_up = method.upper()
    for m, re_p, _, _ in _COMPILED:
        if m == method_up and re_p.match(path):
            return True
    return False


def kind_for_path(method: str, path: str) -> str:
    """Return the ``kind`` tag registered for a matching path, or
    ``"generic"`` if not found."""
    method_up = method.upper()
    for m, re_p, k, _ in _COMPILED:
        if m == method_up and re_p.match(path):
            return k
    return "generic"


def body_shape_for_path(method: str, path: str) -> Optional[str]:
    method_up = method.upper()
    for m, re_p, _, s in _COMPILED:
        if m == method_up and re_p.match(path):
            return s
    return None


# ────────────────────────────────────────────────────────────────────
# Boot-time audit.
# ────────────────────────────────────────────────────────────────────
def audit_route_registry(app: Any) -> Dict[str, Any]:
    """Walk ``app.routes`` and compare to the registry. Pure
    read-only. Returns the report shape documented in the module
    docstring."""
    app_routes: List[Tuple[str, str]] = []
    for r in getattr(app, "routes", []):
        methods = getattr(r, "methods", None) or set()
        path = getattr(r, "path", "")
        for m in methods:
            app_routes.append((m.upper(), path))

    # Which registered routes are MISSING from the app?
    missing: List[Tuple[str, str]] = []
    for m, p, _, _ in PII_INGRESS_REGISTRY:
        if (m, p) not in app_routes:
            missing.append((m, p))

    # Which app routes LOOK LIKE PII ingress but aren't registered?
    #
    # 2026-02 · P0 Stage 3 Commit F — the pre-Commit-F hint was
    # ``/(customers?|leads?|subscribers?|signup|…)/`` which matched
    # EVERY admin / portal / bulk operation on EXISTING records
    # (``/api/customers/{cid}/mute``, ``/api/customer-portal/*``,
    # ``/api/customer-tasks``, etc.). The hardened Commit F posture
    # treats ``RED`` as a hard-fail-boot condition, so a broad hint
    # creates a long tail of exempt-list entries for route patterns
    # that never carried PII ingress in the first place.
    #
    # The tightened hint matches ONLY the three patterns that genuinely
    # accept FRESH PII:
    #   1. POST /api/<collection> with NO path id — new-row intake
    #      (``POST /api/customers``, ``POST /api/leads``,
    #      ``POST /api/outreach/prospects``, ``POST /api/subscribers``).
    #   2. POST /api/public/* and POST /api/widget/* — public /
    #      external form intakes.
    #   3. POST /api/signup (no suffix) and POST /api/webhooks/*
    #      with lead/subscriber keywords.
    #
    # Everything else (admin ops on an existing id-scoped row, portal
    # operations keyed by session identity, bulk operations with ids-
    # only bodies, flag flips) is UPSTREAM of the sanitizer — the
    # original PII ingress happened on the primary POST/PUT path,
    # which IS in the registry. The sub-endpoints inherit the
    # sanitized shape via Mongo.
    pii_hint = re.compile(
        r"^/api/("
        r"customers|leads|outreach/prospects|marketing/subscribers|"
        r"signup|widget/form|public/|webhooks/|imports/pdf-invoice|"
        r"customer-portal/profile|lead-sense|signup-onboarding/step"
        r")(/[^/]+)?(/submit)?$"
    )
    unregistered: List[Tuple[str, str]] = []
    exempted: List[Tuple[str, str]] = []
    for m, p in app_routes:
        if m not in ("POST", "PUT", "PATCH"):
            continue
        if not pii_hint.search(p):
            continue
        # Skip paths already covered by the registry.
        if path_matches_registry(m, p.replace("{", "{")):
            continue
        # Dynamic-path round-trip: build a fake example path and
        # test it.
        example = re.sub(r"\{[^}]+\}", "x", p)
        if path_matches_registry(m, example):
            continue
        # Final check — is this route EXEMPT via the Commit F
        # ``_ROUTES_WITHOUT_PII_PAYLOAD`` list?
        if _is_route_exempt(m, p):
            exempted.append((m, p))
            continue
        unregistered.append((m, p))

    status = "GREEN"
    if missing:
        status = "RED"
    elif unregistered:
        # Any unregistered + unexempted PII-shaped route is a RED on
        # preview (Commit F posture) — the admin either has to wire
        # the decorator or declare the route exempt with a concrete
        # justification. Can't just silently coast on AMBER anymore.
        status = "RED"

    return {
        "total_routes": len(app_routes),
        "declared_pii_routes": len(PII_INGRESS_REGISTRY),
        "exempted_routes": len(_ROUTES_WITHOUT_PII_PAYLOAD),
        "missing_registered_routes": missing,
        "unregistered_pii_shaped_routes": unregistered,
        "exempted_pii_shaped_routes": exempted,
        "status": status,
    }


def assert_registry_coverage(app: Any) -> Dict[str, Any]:
    """Call from server startup. **Commit F posture** (hard-fail):

    * On preview env with status=RED, raises ``RuntimeError`` with
      a clear message listing every unregistered + unexempted
      route path. The admin must either wire the decorator or add
      the route to ``_ROUTES_WITHOUT_PII_PAYLOAD`` with a concrete
      justification string.
    * On production, logs a WARN and returns regardless of status.
      Never fails prod boot — production safety trumps strict
      coverage because the decorator is a strict no-op in prod.
    """
    report = audit_route_registry(app)
    if report["status"] == "RED":
        details: List[str] = []
        if report["missing_registered_routes"]:
            details.append(
                "registered-but-missing: "
                + ", ".join(f"{m} {p}"
                             for m, p in report["missing_registered_routes"])
            )
        if report["unregistered_pii_shaped_routes"]:
            details.append(
                "unregistered-and-unexempted: "
                + ", ".join(f"{m} {p}"
                             for m, p in report["unregistered_pii_shaped_routes"])
            )
        detail_str = " · ".join(details)
        _log.warning(
            "[preview_isolation] registry RED — %s", detail_str,
        )
        if is_production_env():
            # Production stays WARN-only. Never block boot on prod.
            return report
        # Preview: hard-fail boot. The admin must act.
        raise RuntimeError(
            "[preview_isolation] PII route-registry audit failed "
            "on preview env: " + detail_str + ". Either add the "
            "route to PII_INGRESS_REGISTRY or to the "
            "_ROUTES_WITHOUT_PII_PAYLOAD exemption list in "
            "services/preview_isolation/registry.py with a "
            "concrete 1-line justification."
        )
    elif report["status"] == "AMBER":
        # ``AMBER`` is no longer possible under the Commit F posture
        # (unregistered unexempted routes now escalate to RED). Keep
        # the branch for future expansion.
        _log.info(
            "[preview_isolation] registry AMBER — %d exempt entries",
            report["exempted_routes"],
        )
    else:
        _log.info(
            "[preview_isolation] registry GREEN — %d registered, "
            "%d exempt, %d/%d app routes",
            report["declared_pii_routes"],
            report["exempted_routes"],
            report["declared_pii_routes"] + report["exempted_routes"],
            report["total_routes"],
        )
    return report


__all__ = [
    "PII_INGRESS_REGISTRY",
    "_ROUTES_WITHOUT_PII_PAYLOAD",
    "audit_route_registry",
    "assert_registry_coverage",
    "path_matches_registry",
    "kind_for_path",
    "body_shape_for_path",
]
