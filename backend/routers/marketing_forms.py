"""Feb-2026 · Slice H1 — Public Form Builder backend.

Two surfaces:

* Admin (``/api/admin/forms/*``) — CRUD for form definitions + read-
  access on submissions. Standard JWT admin auth.
* Public (``/api/widget/form/*``) — schema fetch + submit, called by
  the widget JS bundle on the tenant's marketing site. Uses
  :func:`routers.widget_config.require_widget_auth` (public widget key
  + Origin allowlist).

Cloudflare Turnstile:
* When ``TURNSTILE_SECRET`` is set in ``/app/backend/.env`` we require
  and verify a ``turnstile_token`` on every public submit.
* When it is unset we log a single startup warning (from
  :func:`log_turnstile_status_once`) and accept submissions without
  verification. This keeps dev + preview builds unblocked.

Post-submit actions (per-form ``submit_config``):
* ``creates`` — ``"lead"`` (default), ``"customer"``, or ``"both"``.
* ``confirmation_email_template_id`` — M3 template rendered against
  the submission answers and dropped into ``marketing_deliveries``
  (mocked, same pipeline as M5/M6).
* ``drip_sequence_id`` — enrol the resulting lead/customer into an M5
  sequence via ``marketing_drip_enrolments``.
* ``admin_bell`` — fan the classic Slice-3D bell (default True).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, model_validator

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from routers.widget_config import require_widget_auth

router = APIRouter(tags=["Marketing Forms"])

# ─── Turnstile helpers ────────────────────────────────────────────────

TURNSTILE_VERIFY_URL = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)
_TURNSTILE_WARNED = False


def _turnstile_secret() -> str:
    return (os.environ.get("TURNSTILE_SECRET") or "").strip()


def log_turnstile_status_once() -> None:
    """Called once from server.py startup. Emits a single WARN when
    the secret is missing so ops know verification is bypassed."""
    global _TURNSTILE_WARNED
    if _TURNSTILE_WARNED:
        return
    _TURNSTILE_WARNED = True
    if not _turnstile_secret():
        logger.warning(
            "[h1] turnstile disabled — TURNSTILE_SECRET missing; "
            "form submissions will NOT be verified"
        )
    else:
        logger.info("[h1] turnstile verification ENABLED")


async def _verify_turnstile(token: Optional[str], remote_ip: Optional[str]) -> None:
    """Hard-verify a Turnstile token. No-op when secret is unset."""
    secret = _turnstile_secret()
    if not secret:
        return  # graceful bypass
    if not token:
        raise HTTPException(400, "Missing turnstile_token")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                TURNSTILE_VERIFY_URL,
                data={
                    "secret": secret,
                    "response": token,
                    **({"remoteip": remote_ip} if remote_ip else {}),
                },
            )
            payload = r.json()
    except Exception as exc:
        logger.warning("[h1] turnstile verify request failed: %s", exc)
        raise HTTPException(502, "turnstile verification unavailable")
    if not payload.get("success"):
        logger.info("[h1] turnstile rejected: %s", payload)
        raise HTTPException(400, "turnstile verification failed")


# ─── Field / form models ─────────────────────────────────────────────

# GH-Fix: broadened field type set to match the tester's spec — every
# widget builder type round-trips: text, email, phone, textarea,
# number, url, address_google, dropdown, multiselect, checkbox, radio,
# date, file, select (alias for dropdown for backwards compat).
#
# CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. Adds ``"section"``
# as a LAYOUT-ONLY marker: renders a section heading in the public
# form but collects no submission value. Skips the usual ``name`` /
# submission-key handling in ``_validate_field_defs``.
#
# TD-52 · Feb-2026 — palette expansion. Four new field types land
# with narrowly-scoped server contracts:
#   * ``signature``         — submission value is a data URL
#                             (``data:image/png;base64,…``). Stored
#                             verbatim; no server-side canvas handling.
#   * ``address_manual``    — composite 4-input field. Submission
#                             value is a nested dict
#                             ``{line1, city, state, zip}``.
#                             Clients may submit the composite via the
#                             widget OR flatten to 4 separate keys
#                             (``<name>_line1`` etc.); both forms are
#                             accepted by the dispatcher. Any missing
#                             component is simply omitted.
#   * ``rating_stars``      — integer 1..5. Enforced at submit time.
#   * ``file_multi_upload`` — multi-file picker. Submission uses the
#                             existing ``/widget/form/{fid}/submit-
#                             multipart`` endpoint; each file lands
#                             as a separate form-data part keyed on
#                             the field name.
_FIELD_TYPES = {
    "text", "email", "phone", "textarea", "number", "url", "date",
    "address_google", "dropdown", "select", "multiselect",
    "checkbox", "radio", "file", "section",
    # TD-52 palette expansion.
    "signature", "address_manual", "rating_stars", "file_multi_upload",
    # TD-54 · Feb-2026 — multi-step forms. ``page_break`` is a LAYOUT
    # marker (sibling of ``section``) that splits the form into pages
    # for the widget's Prev/Next renderer.  Server sees the full
    # ``answers`` dict on final submit regardless of pagination —
    # pagination is a client concern.
    "page_break",
}
_OPTIONS_REQUIRED_TYPES = {"dropdown", "select", "multiselect", "radio"}
# CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. Layout-only types
# have no submission value. Skipped for duplicate-name checks + do
# not require ``name`` to be non-empty.
_LAYOUT_TYPES = {"section", "page_break"}  # TD-54 adds page_break
_COLUMN_SPAN_VALUES = {"full", "half"}
# TD-54 · Feb-2026 — ``page_title`` optional metadata on ``page_break``
# fields.  Shown as the step label in the widget's Prev/Next renderer;
# capped at 60 chars (same max as other short-form metadata).
_PAGE_TITLE_MAX_LEN = 60

# TD-52 · Feb-2026 — subset of the palette that carries extra server-
# side submission sanity beyond the generic required-check:
#   * ``rating_stars`` — if a non-null value is submitted it MUST be
#     an integer in [1, 5].  Numeric strings (``"3"``) are coerced
#     for operator-friendliness; anything else 422s.
# ``signature`` / ``address_manual`` / ``file_multi_upload`` are
# accepted as-is; their shape is loose by design (data URL / nested
# dict / list of filenames) and clients may legitimately omit any
# subcomponent.  The required-check elsewhere in this module still
# applies.
_RATING_STARS_MIN = 1
_RATING_STARS_MAX = 5


def _coerce_rating_stars(val: Any) -> Optional[int]:
    """Return the int form of ``val`` if it falls in [1, 5], else
    ``None``. Accepts ints, bools-as-ints (0/1 only — bool is NOT a
    valid rating though), and numeric strings. Everything else
    returns None so the caller can 422."""
    if val is None:
        return None
    if isinstance(val, bool):
        # Avoid True/False silently coercing to 1/0 — ratings are
        # explicitly numeric.
        return None
    if isinstance(val, int):
        return val if _RATING_STARS_MIN <= val <= _RATING_STARS_MAX else None
    if isinstance(val, float):
        # NaN / inf are never valid; ``int(float("nan"))`` raises.
        if val != val or val in (float("inf"), float("-inf")):
            return None
        iv = int(val)
        if iv != val:
            return None
        return iv if _RATING_STARS_MIN <= iv <= _RATING_STARS_MAX else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            iv = int(s)
        except (TypeError, ValueError):
            return None
        return iv if _RATING_STARS_MIN <= iv <= _RATING_STARS_MAX else None
    return None


def _validate_td52_field_values(fields: List[Dict[str, Any]],
                                 payload: Dict[str, Any]) -> None:
    """Per-type submission sanity for the TD-52 palette.

    Mutates ``payload`` in-place: when the author submits a numeric
    string rating (``"4"``) we coerce it to the int ``4`` so
    downstream lead-extraction / drip templating sees a clean type.
    Raises 422 on hard violations.
    """
    for f in fields:
        ftype = f.get("type")
        if ftype != "rating_stars":
            continue
        key_name = f.get("name") or f.get("id")
        if not key_name:
            continue
        # Resolve the value under either the ``name`` or ``id`` key.
        if key_name in payload:
            raw = payload.get(key_name)
            payload_key = key_name
        elif f.get("id") in payload:
            raw = payload.get(f["id"])
            payload_key = f["id"]
        else:
            # Missing optional rating is fine — required-check runs
            # before this helper, so a missing REQUIRED rating has
            # already errored out upstream.
            continue
        if raw in (None, "") or (isinstance(raw, str) and not raw.strip()):
            continue
        coerced = _coerce_rating_stars(raw)
        if coerced is None:
            raise HTTPException(
                422,
                f"field '{f.get('name') or f.get('id')}': "
                f"rating_stars must be an integer in [1, 5]",
            )
        payload[payload_key] = coerced

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,63})$")
_FIELD_ID_RE = re.compile(r"[^a-z0-9]+")


def _norm_slug(v: str) -> str:
    v = (v or "").strip().lower()
    v = re.sub(r"[^a-z0-9-]+", "-", v).strip("-")
    if not v:
        raise HTTPException(422, "slug cannot be empty")
    if not _SLUG_RE.match(v):
        raise HTTPException(422, f"'{v}' is not a valid slug")
    return v[:64]


def _norm_field_id(v: str) -> str:
    """Deterministic field id derived from ``name`` (or explicit id).
    Lowercase, alphanumeric-plus-underscore, ≤ 60 chars."""
    v = (v or "").strip().lower()
    v = _FIELD_ID_RE.sub("_", v).strip("_")
    return v[:60] or "field"


class FormField(BaseModel):
    # Both ``id`` and ``name`` are stored. ``id`` is auto-generated
    # from ``name`` when the client doesn't provide one, so submissions
    # can key by either while the frontend renders by ``id``/``order``.
    #
    # CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. ``name`` is now
    # optional so ``"section"``-type layout markers can omit it. Every
    # non-layout type still requires a non-empty name; enforced in
    # ``_validate_field_defs`` (Pydantic-level laxity kept minimal so
    # the type-based rule is the single source of truth).
    id: Optional[str] = Field(None, max_length=60)
    name: Optional[str] = Field(None, max_length=60)
    label: str = Field(..., min_length=1, max_length=120)
    type: str = Field(..., description=f"one of {sorted(_FIELD_TYPES)}")
    required: bool = False
    placeholder: Optional[str] = Field(None, max_length=120)
    options: Optional[List[str]] = None
    # Freeform ``validation`` blob — passed through untouched for now
    # (min/max/pattern etc. — the widget UI will enforce client-side;
    # server-side enforcement is best-effort forward compat).
    validation: Optional[Dict[str, Any]] = None
    # Client can set explicit order; when absent we assign the array
    # index on save.
    order: Optional[int] = None
    # CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. Optional layout
    # hint. ``None`` means "renderer default" — today the widget +
    # ``ThemedFormShell`` render every field full-width, so ``None``
    # and ``"full"`` are equivalent on the wire. Left truly optional
    # (no server-side default coercion) so pre-Phase-1 forms round-
    # trip byte-identical.
    column_span: Optional[Literal["full", "half"]] = None
    # TD-54 · Feb-2026 — multi-step forms. Optional step label shown
    # on the widget's Prev/Next progress indicator when this field is
    # a ``page_break``. Ignored for every other field type (preserved
    # on round-trip but not surfaced).  Capped at 60 chars matching
    # ``name`` / ``id``.
    page_title: Optional[str] = Field(None, max_length=_PAGE_TITLE_MAX_LEN)
    # CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53).
    # Optional conditional-logic rule. When set, the field is hidden
    # (and its ``required`` is suppressed, and its submitted value is
    # dropped before lead-extraction) unless the referenced parent
    # field's current answer satisfies the operator. Shape:
    #
    #   {
    #     "field_id": "<id of another field on the same form>",
    #     "operator": "eq" | "neq" | "contains",
    #     "value":    <string | bool | number | list of strings>
    #   }
    #
    # Semantics:
    #   * "eq"       — parent answer == value   (case-sensitive)
    #   * "neq"      — parent answer != value   (case-sensitive)
    #   * "contains" — list/multiselect parent includes value; OR
    #                  string parent includes value substring
    #
    # Server-side validation (in ``_validate_field_defs``) ensures:
    #   * ``operator`` is one of the three enum values.
    #   * ``field_id`` references an existing non-layout field on the
    #     same form (dangling refs rejected at save time).
    #   * No circular reference chain (A show_if B, B show_if A, OR
    #     deeper A→B→C→A loops).
    #   * A field cannot ``show_if`` itself.
    #   * ``value`` is accepted free-form; its type is NOT constrained
    #     at save time — the evaluator coerces/compares at runtime so
    #     the author can target a number field with a stringified
    #     value (``"5"`` vs ``5``) and still get the expected result.
    #
    # Legacy forms (no ``show_if`` on any field) round-trip byte-
    # identical — the ``_is_field_visible`` evaluator short-circuits
    # to True when ``show_if`` is None.
    show_if: Optional[Dict[str, Any]] = None


# TD-51 · Feb-2026 — accepted ``submit_config.creates`` enum.  Lives
# at module scope so the pydantic validator + the dispatcher both
# reference ONE source of truth. Order is semantic:
#   * ``lead`` / ``customer`` / ``both`` — pre-TD-51 shipping set.
#   * ``booking`` — new row in ``db.job_requests`` (operator triage).
#   * ``service_log`` — new row in ``db.service_reports`` with
#     ``source="marketing_form"`` + null ``tech_id`` / ``job_id`` so
#     the tech post-service dashboards don't surface them.
#   * ``quote_request`` — new row in ``db.lead_requests`` (quote
#     triage queue, distinct from the admin-dispatch flow in
#     ``routers/lead_requests.py`` which uses a different document
#     shape under ``db.lead_request_dispatches``).
_CREATES_VALUES = frozenset(
    ("lead", "customer", "both",
     "booking", "service_log", "quote_request"),
)
# TD-51 · subject_kind values that the drip-enrolment pipeline knows
# how to handle. New destinations are deliberately NOT enrolled —
# they are operational triage, not customer-facing cadence surfaces.
_DRIP_SUBJECT_KINDS = frozenset(("lead", "customer"))


class SubmitConfig(BaseModel):
    # GH-Fix: submit_config wired per tester brief.
    # TD-51 · Feb-2026 — ``creates`` widened to admit three new
    # single-value destinations: ``booking`` (→ ``db.job_requests``
    # operator-triage queue), ``service_log`` (→ ``db.service_reports``
    # with ``source="marketing_form"`` marker), ``quote_request``
    # (→ ``db.lead_requests`` quote-queue). Confirmation-email + drip
    # plumbing is reused via ``_pick_subject``; drip enrolment is
    # intentionally SKIPPED for the three new kinds (they are
    # operational triage entries, not marketing cadence surfaces).
    creates: str = Field(
        "lead",
        description=(
            'one of "lead" | "customer" | "both" | "booking" | '
            '"service_log" | "quote_request"'
        ),
    )
    confirmation_email_template_id: Optional[str] = None
    drip_sequence_id: Optional[str] = None
    admin_bell: bool = True

    @model_validator(mode="after")
    def _check_creates(self):  # noqa: D401
        v = (self.creates or "lead").lower().strip()
        if v not in _CREATES_VALUES:
            raise ValueError(
                'creates must be one of "lead" | "customer" | "both" | '
                '"booking" | "service_log" | "quote_request"'
            )
        self.creates = v
        return self


class FormIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    slug: Optional[str] = None
    # GH-Fix: fields list now MUST be non-empty (min_items=1). A form
    # with zero fields is meaningless.
    fields: List[FormField] = Field(..., min_length=1)
    submit_button_label: str = Field("Send", max_length=40)
    success_message: str = Field(
        "Thanks! We'll be in touch shortly.", max_length=280
    )
    submit_config: SubmitConfig = Field(default_factory=SubmitConfig)
    # ``notify_admin_bell`` kept for backwards compat but the canonical
    # switch is now ``submit_config.admin_bell``.
    notify_admin_bell: Optional[bool] = None
    # K34 · Feb-2026 — unified form theme (preset + colors + font).
    # Untyped dict here so a future preset change on the frontend
    # doesn't require a Pydantic schema bump. Defaults to None so
    # legacy forms render with the app's default look.
    theme: Optional[Dict[str, Any]] = None
    # CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. Hero designer
    # payload. Persisted opaquely (frontend owns the sub-schema); the
    # shape below is the contract enforced by the builder UI and
    # renderers:
    #
    #   {
    #     "heading_html":     "<p>...</p>",     # Tiptap HTML output
    #     "subheading_html":  "<p>...</p>",     # Tiptap HTML output
    #     "background": {                        # discriminated union
    #       "kind": "color" | "image" | "gradient",
    #       # kind=color:    "color": "#hex"
    #       # kind=image:    "url": "https://...",
    #       #                "overlay_opacity": int 0-100 (default 30)
    #       # kind=gradient: "angle_deg": int, "from": "#hex", "to": "#hex"
    #     },
    #     "badge": {                             # optional 'Special Offer'
    #       "url": "https://...",                # from MediaLibraryPicker
    #       "alt_text": "..."
    #     }
    #   }
    #
    # Mirrors the K34 ``theme`` pattern — untyped-dict-through so the
    # frontend can evolve the sub-schema without a backend bump. None
    # for pre-Phase-1 forms → renderers skip hero and render the form
    # body only.
    hero: Optional[Dict[str, Any]] = None


class FormPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    fields: Optional[List[FormField]] = None
    submit_button_label: Optional[str] = Field(None, max_length=40)
    success_message: Optional[str] = Field(None, max_length=280)
    submit_config: Optional[SubmitConfig] = None
    notify_admin_bell: Optional[bool] = None
    active: Optional[bool] = None
    # K34 · Feb-2026 — patch surface for the unified form theme.
    theme: Optional[Dict[str, Any]] = None
    # CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. Patch surface
    # for the hero designer payload. See ``FormIn.hero`` docstring for
    # the frontend-owned shape.
    hero: Optional[Dict[str, Any]] = None


class FormSubmit(BaseModel):
    # GH-Fix: accept both ``data`` and ``answers`` (canonical). The
    # public-facing spec uses ``answers``; the initial H1 implementation
    # used ``data``. Both are normalised server-side.
    data: Optional[Dict[str, Any]] = None
    answers: Optional[Dict[str, Any]] = None
    turnstile_token: Optional[str] = None
    page_url: Optional[str] = Field(None, max_length=500)


# ═══════════════════════════════════════════════════════════════════
# CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53) ·
# ``show_if`` conditional-logic engine.
# ═══════════════════════════════════════════════════════════════════

_SHOW_IF_OPERATORS = frozenset({"eq", "neq", "contains"})


def _validate_show_if_rules(
    normalised: List[Dict[str, Any]],
) -> None:
    """Validate every field's ``show_if`` rule AFTER ids have been
    normalised. Mutates nothing; raises HTTPException(422) on the
    first violation. Call site: :func:`_validate_field_defs` right
    before it returns.

    Guards:
      * ``operator`` must be one of ``_SHOW_IF_OPERATORS``.
      * ``field_id`` must reference an existing field on the same
        form (by id). Dangling references rejected.
      * A field cannot ``show_if`` itself (``field_id`` == own id).
      * No circular chain: build a dep graph (``child_id →
        parent_id``) and run a DFS cycle check. Loops are rejected
        so the renderer evaluator can't infinite-recurse.
      * Layout markers (``section`` etc.) MAY carry ``show_if`` —
        hiding a whole section via a parent toggle is a valid UX
        pattern. The visibility evaluator treats them the same.
    """
    ids_by_fid = {f["id"]: f for f in normalised}
    deps: Dict[str, str] = {}  # child_id -> parent_id

    for f in normalised:
        rule = f.get("show_if")
        if rule is None:
            continue
        if not isinstance(rule, dict):
            raise HTTPException(
                422,
                f"field '{f.get('name') or f['id']}': show_if must be an object",
            )
        op = rule.get("operator")
        if op not in _SHOW_IF_OPERATORS:
            raise HTTPException(
                422,
                f"field '{f.get('name') or f['id']}': show_if.operator "
                f"must be one of {sorted(_SHOW_IF_OPERATORS)}",
            )
        parent_fid = rule.get("field_id")
        if not isinstance(parent_fid, str) or not parent_fid:
            raise HTTPException(
                422,
                f"field '{f.get('name') or f['id']}': show_if.field_id "
                "is required and must be a non-empty string",
            )
        if parent_fid == f["id"]:
            raise HTTPException(
                422,
                f"field '{f.get('name') or f['id']}': show_if.field_id "
                "cannot reference itself",
            )
        if parent_fid not in ids_by_fid:
            raise HTTPException(
                422,
                f"field '{f.get('name') or f['id']}': show_if.field_id "
                f"'{parent_fid}' does not match any field on this form",
            )
        # ``value`` is intentionally free-form; the evaluator coerces
        # at runtime (string vs number vs bool). We only enforce
        # presence of the key.
        if "value" not in rule:
            raise HTTPException(
                422,
                f"field '{f.get('name') or f['id']}': show_if.value "
                "key is required (may be null / empty string / etc.)",
            )
        deps[f["id"]] = parent_fid

    # Cycle detection — DFS with path-tracking. ``deps`` is a sparse
    # child → parent map (each child has at most one parent, so this
    # is really a forest of upside-down trees + any cycles).
    for start in deps:
        seen: set = set()
        node = start
        while node in deps:
            if node in seen:
                raise HTTPException(
                    422,
                    f"show_if circular reference detected starting at "
                    f"field '{start}' → walked chain: "
                    f"{' → '.join(list(seen) + [node])}",
                )
            seen.add(node)
            node = deps[node]


def _coerce_for_compare(v: Any) -> Any:
    """Normalize a value for ``show_if`` operator comparison. Strings
    are stripped; numeric values are left as-is; bools are left as-
    is. ``None`` + empty-after-strip collapse to ``None`` so a field
    with "" and a field that was never answered compare equal."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return v


def _is_field_visible(
    field_dict: Dict[str, Any],
    answers: Dict[str, Any],
    fields_by_id: Dict[str, Dict[str, Any]],
) -> bool:
    """Evaluate a field's ``show_if`` rule against the submitted
    answers. Returns True when:

      * ``show_if`` is None (no rule → always visible), OR
      * The rule evaluates True under the operator semantics.

    Operator semantics (coerced via ``_coerce_for_compare``):
      * ``"eq"``       — parent_answer == rule.value
      * ``"neq"``      — parent_answer != rule.value
      * ``"contains"`` — if parent_answer is a list/tuple: value in it
                         if parent_answer is a string: value substring
                         anything else: False (defensive — malformed
                                        data doesn't fire the rule)

    Looks up the parent field's answer by BOTH ``name`` and ``id``
    (the widget may post either shape — matches the pattern used by
    the required-field check elsewhere in this module).
    """
    rule = field_dict.get("show_if")
    if rule is None:
        return True

    parent_fid = rule.get("field_id")
    parent = fields_by_id.get(parent_fid or "")
    if parent is None:
        # Dangling at runtime (shouldn't happen — save-time validator
        # catches it, but belt-and-suspenders for forms that
        # pre-date TD-53).
        return True

    parent_val = answers.get(parent.get("name") or "") if parent.get("name") else None
    if parent_val is None:
        parent_val = answers.get(parent_fid)

    op = rule.get("operator")
    target = rule.get("value")
    lhs = _coerce_for_compare(parent_val)
    rhs = _coerce_for_compare(target)

    if op == "eq":
        return lhs == rhs
    if op == "neq":
        return lhs != rhs
    if op == "contains":
        if isinstance(parent_val, (list, tuple)):
            # Compare against raw list members (don't strip inner
            # whitespace — authors may legitimately target "  "
            # answers from a checkbox group).
            return target in parent_val
        if isinstance(parent_val, str) and isinstance(target, str):
            return target in parent_val
        return False
    return True  # unknown operator — fail open (save-time validator
                 # has already rejected these, so this is defensive).


def _validate_field_defs(fields: List[FormField]) -> List[Dict[str, Any]]:
    """Validate + normalise. Auto-populates ``id`` and ``order``.
    Returns the plain-dict list ready for persistence.

    CUS-Marketing-Form-Builder · Feb-2026 — Phase 1 changes:
      * ``"section"``-type fields are LAYOUT markers — no submission
        value, ``name`` is optional (auto-derived from ``label`` when
        missing), and duplicate-name checks are skipped for them.
      * ``column_span`` when present MUST be ``"full"`` or ``"half"``
        — anything else raises 422. ``None`` is allowed and means
        "renderer default" (currently full-width).
    """
    if not fields:
        raise HTTPException(422, "form must have at least one field")
    seen_names: set = set()
    seen_ids: set = set()
    normalised: List[Dict[str, Any]] = []
    for idx, f in enumerate(fields):
        if f.type not in _FIELD_TYPES:
            raise HTTPException(422, f"field '{f.name}': unsupported type '{f.type}'")
        is_layout = f.type in _LAYOUT_TYPES
        # Non-layout fields still require a non-empty ``name``. Layout
        # markers may omit it (they're addressed by ``id``/``order``
        # only and never appear in submission answers).
        if not is_layout and not (f.name or "").strip():
            raise HTTPException(
                422,
                f"field of type '{f.type}' requires a non-empty name",
            )
        if not is_layout and f.name in seen_names:
            raise HTTPException(422, f"duplicate field name '{f.name}'")
        if not is_layout:
            seen_names.add(f.name)
        if f.type in _OPTIONS_REQUIRED_TYPES and not f.options:
            raise HTTPException(
                422,
                f"field '{f.name}': {f.type} fields need options",
            )
        # ``column_span`` — enum-validate. Pydantic v2 also enforces
        # via ``Literal`` at model-parse time, but re-checking here
        # gives a clearer error message for the dict-input PATCH path.
        if f.column_span is not None and f.column_span not in _COLUMN_SPAN_VALUES:
            raise HTTPException(
                422,
                f"field '{f.name or f.label}': column_span must be "
                f"one of {sorted(_COLUMN_SPAN_VALUES)}",
            )
        # Layout markers derive their id from ``label`` (or a stable
        # ``section-{idx}`` fallback) so they still have a
        # deterministic key for React ``key=`` props on the renderer.
        base_key = f.id or f.name or (f.label if is_layout else "")
        fid = _norm_field_id(base_key or f"section_{idx}")
        # Ensure id uniqueness (auto-suffix if collides).
        base = fid; n = 2
        while fid in seen_ids:
            fid = f"{base}_{n}"; n += 1
        seen_ids.add(fid)
        d = f.dict()
        d["id"] = fid
        d["order"] = f.order if isinstance(f.order, int) else idx
        normalised.append(d)
    # TD-53 · validate show_if rules AFTER ids are stable.
    _validate_show_if_rules(normalised)
    return normalised


async def _validate_submit_config(sc: Optional[SubmitConfig],
                                     tenant_id: str) -> Dict[str, Any]:
    """Ensure referenced M3 template + M5 sequence exist in this
    tenant (and template.channel == 'email' when configured for the
    confirmation email). Returns the plain dict for persistence."""
    if sc is None:
        sc = SubmitConfig()
    if sc.confirmation_email_template_id:
        tpl = await db.marketing_templates.find_one(
            {"id": sc.confirmation_email_template_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "channel": 1, "active": 1},
        )
        if not tpl:
            raise HTTPException(
                422, "confirmation_email_template_id not found in this tenant")
        if tpl.get("channel") != "email":
            raise HTTPException(
                422, "confirmation_email_template_id must be an email template")
    if sc.drip_sequence_id:
        seq = await db.marketing_sequences.find_one(
            {"id": sc.drip_sequence_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1},
        )
        if not seq:
            raise HTTPException(
                422, "drip_sequence_id not found in this tenant")
    return sc.dict()


# ═══════════════════════════════════════════════════════════════════════
# Admin routes — full JWT auth
# ═══════════════════════════════════════════════════════════════════════
@router.post("/admin/forms", status_code=201)
async def create_form(body: FormIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    normalised_fields = _validate_field_defs(body.fields)
    slug = _norm_slug(body.slug or body.name)
    dupe = await db.marketing_forms.find_one(
        {"tenant_id": tenant["id"], "slug": slug}, {"_id": 0, "id": 1}
    )
    if dupe:
        raise HTTPException(409, f"slug '{slug}' already exists for this tenant")

    # Reconcile legacy notify_admin_bell → submit_config.admin_bell.
    sc = body.submit_config
    if body.notify_admin_bell is not None:
        sc = sc.copy(update={"admin_bell": body.notify_admin_bell})
    submit_cfg = await _validate_submit_config(sc, tenant["id"])

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": body.name,
        "slug": slug,
        "fields": normalised_fields,
        "submit_button_label": body.submit_button_label,
        "success_message": body.success_message,
        "submit_config": submit_cfg,
        # Legacy mirror for existing consumers.
        "notify_admin_bell": submit_cfg["admin_bell"],
        "active": True,
        "created_by": user["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "submission_count": 0,
        # K34 · Feb-2026 — untyped dict passthrough. None until the
        # builder picks a preset / customizes colors.
        "theme": body.theme,
        # CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. Untyped
        # dict passthrough. None for legacy / pre-Phase-1 forms.
        "hero": body.hero,
        # Feb-2026 · Form Builder P2#12 Phase 1 Commit 2 — version
        # counter. Byte-identical to pre-Phase-1 for callers that
        # never read it; set to 1 on create. Mutates alongside the
        # new ``db.marketing_form_versions`` collection via
        # ``_snapshot_form_version`` below.
        "version": 1,
    }
    await db.marketing_forms.insert_one(doc)
    doc.pop("_id", None)
    await _snapshot_form_version(doc, user.get("id") or "", action="create")
    return doc


async def _snapshot_form_version(
    form_doc: dict, actor_id: str, action: str = "update",
) -> None:
    """Write a snapshot row to ``db.marketing_form_versions``.

    Pattern mirrors ``routers/form_templates.py:_ensure_seed`` +
    ``put_template`` but keeps the live ``marketing_forms`` doc as
    the "current" view — snapshots are a sibling-collection audit
    trail, not a replacement for the live row. This preserves
    runtime fields (``slug``, ``submission_count``, ``created_at``,
    ``active``) on the live doc while making every schema edit
    rollback-able.

    ``action`` is one of ``"create" | "update" | "revert"`` so the
    history UI can show operators which versions were rollbacks.
    """
    snap = {
        "id": new_id(),
        "tenant_id": form_doc["tenant_id"],
        "form_id": form_doc["id"],
        "version": form_doc.get("version") or 1,
        "action": action,
        "name": form_doc.get("name"),
        "fields": form_doc.get("fields") or [],
        "submit_config": form_doc.get("submit_config"),
        "theme": form_doc.get("theme"),
        "hero": form_doc.get("hero"),
        "submit_button_label": form_doc.get("submit_button_label"),
        "success_message": form_doc.get("success_message"),
        "actor_id": actor_id,
        "at": now_iso(),
    }
    try:
        await db.marketing_form_versions.insert_one(snap)
    except Exception as _e:  # noqa: BLE001
        logger.warning(
            "[forms-versioning] snapshot insert failed form_id=%s v=%s err=%s",
            form_doc.get("id"), form_doc.get("version"), _e,
        )


@router.get("/admin/forms")
async def list_forms(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    rows = await db.marketing_forms.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return rows


@router.get("/admin/forms/{fid}")
async def get_form(fid: str,
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    doc = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Form not found")
    return doc


@router.patch("/admin/forms/{fid}")
async def patch_form(fid: str, body: FormPatch,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()}
    if "fields" in updates and updates["fields"] is not None:
        field_objs = [FormField(**f) if isinstance(f, dict) else f
                       for f in updates["fields"]]
        updates["fields"] = _validate_field_defs(field_objs)
    if "submit_config" in updates and updates["submit_config"] is not None:
        sc_obj = (updates["submit_config"] if isinstance(updates["submit_config"], SubmitConfig)
                     else SubmitConfig(**updates["submit_config"]))
        updates["submit_config"] = await _validate_submit_config(sc_obj, tenant["id"])
        # Keep the legacy mirror in sync.
        updates["notify_admin_bell"] = updates["submit_config"]["admin_bell"]
    elif "notify_admin_bell" in updates and updates["notify_admin_bell"] is not None:
        # Mirror the legacy toggle back into submit_config.admin_bell.
        cur = await db.marketing_forms.find_one(
            {"id": fid, "tenant_id": tenant["id"]},
            {"_id": 0, "submit_config": 1},
        )
        base = (cur or {}).get("submit_config") or {}
        base["admin_bell"] = bool(updates["notify_admin_bell"])
        updates["submit_config"] = base
    updates["updated_at"] = now_iso()
    # Feb-2026 · Form Builder P2#12 Phase 1 Commit 2 — version bump
    # on every PATCH that changes any schema-impacting field.
    # ``slug`` + ``active`` are RUNTIME-level and intentionally
    # omitted from the trigger set (keeps the version counter from
    # climbing on operational toggles). Byte-identical response
    # shape for pre-Phase-1 clients that don't key on ``version``.
    _VERSIONED_FIELDS = {
        "name", "fields", "submit_button_label", "success_message",
        "submit_config", "notify_admin_bell", "theme", "hero",
    }
    bump_version = bool(_VERSIONED_FIELDS.intersection(updates.keys()))
    if bump_version:
        _cur_doc = await db.marketing_forms.find_one(
            {"id": fid, "tenant_id": tenant["id"]},
            {"_id": 0, "version": 1},
        )
        updates["version"] = ((_cur_doc or {}).get("version") or 1) + 1
    r = await db.marketing_forms.update_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Form not found")
    updated_doc = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if bump_version and updated_doc:
        await _snapshot_form_version(
            updated_doc, user.get("id") or "", action="update",
        )
    return updated_doc


@router.delete("/admin/forms/{fid}")
async def delete_form(fid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.marketing_forms.delete_one(
        {"id": fid, "tenant_id": tenant["id"]}
    )
    return {"ok": True, "deleted": r.deleted_count}


# ───────────────────────────────────────────────────────────────────
# Feb-2026 · Form Builder P2#12 Phase 1 Commit 2 — version history
# + revert.  Sibling collection ``db.marketing_form_versions`` holds
# a snapshot per schema-impacting edit; runtime fields (``slug``,
# ``submission_count``, ``active``) stay on the live ``marketing_forms``
# doc. Gated by ``require_admin`` — which admits admin / super_admin /
# owner (OWNER-ACCESS-MARKETING-FORMS · Feb-2026) — mirrors the
# sensitivity gate on ``routers/form_templates.py:list_versions``.
# ───────────────────────────────────────────────────────────────────


@router.get("/admin/forms/{fid}/versions")
async def list_form_versions(
    fid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    cur = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1},
    )
    if not cur:
        raise HTTPException(404, "Form not found")
    rows: List[dict] = []
    async for doc in db.marketing_form_versions.find(
        {"tenant_id": tenant["id"], "form_id": fid}, {"_id": 0},
    ).sort("version", -1):
        rows.append(doc)
    return {"versions": rows}


@router.post("/admin/forms/{fid}/revert/{version}")
async def revert_form(
    fid: str,
    version: int,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    live = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not live:
        raise HTTPException(404, "Form not found")
    target = await db.marketing_form_versions.find_one(
        {"tenant_id": tenant["id"], "form_id": fid, "version": version},
        {"_id": 0},
    )
    if not target:
        raise HTTPException(404, f"Version {version} not found")
    # Revert = apply the snapshot's schema fields on top of the live
    # doc + bump to a NEW version so the history timeline reads
    # linearly ("v4 reverts to v2 → v5"). This matches the
    # ``form_templates`` revert pattern: never mutate the historical
    # row; always append.
    next_version = (live.get("version") or 1) + 1
    updates = {
        "name": target.get("name"),
        "fields": target.get("fields") or [],
        "submit_config": target.get("submit_config"),
        "theme": target.get("theme"),
        "hero": target.get("hero"),
        "submit_button_label": target.get("submit_button_label"),
        "success_message": target.get("success_message"),
        "updated_at": now_iso(),
        "version": next_version,
    }
    # Keep the legacy mirror in sync.
    if isinstance(updates.get("submit_config"), dict):
        updates["notify_admin_bell"] = bool(
            updates["submit_config"].get("admin_bell"))
    await db.marketing_forms.update_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    reverted = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    await _snapshot_form_version(
        reverted, user.get("id") or "", action="revert",
    )
    return reverted


@router.get("/admin/forms/{fid}/submissions")
async def list_form_submissions(fid: str,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant),
                                    limit: int = 100):
    exists = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    )
    if not exists:
        raise HTTPException(404, "Form not found")
    rows = await db.form_submissions.find(
        {"tenant_id": tenant["id"], "form_id": fid},
        {"_id": 0},
    ).sort("created_at", -1).to_list(min(max(1, int(limit or 100)), 500))
    return rows


# ═══════════════════════════════════════════════════════════════════════
# Public widget routes — X-Widget-Key + Origin allowlist
# ═══════════════════════════════════════════════════════════════════════
@router.get("/widget/form/{fid}")
async def get_widget_form(fid: str,
                             tenant: Dict[str, Any] = Depends(require_widget_auth)):
    """Return the public-safe schema of a form (no internal fields)."""
    doc = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"], "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "slug": 1, "fields": 1,
         "submit_button_label": 1, "success_message": 1,
         # K34 · Feb-2026 — surface the theme so the public widget
         # renderer can apply it. Absent for legacy forms → renderer
         # falls back to the app default.
         "theme": 1,
         # CUS-Marketing-Form-Builder · Feb-2026 — Phase 1. Surface
         # the hero designer payload so the widget can render the
         # heading + subheading + background. Absent for legacy
         # forms → renderer skips the hero band.
         "hero": 1},
    )
    if not doc:
        raise HTTPException(404, "Form not found or not active")
    return doc


@router.post("/widget/form/{fid}/submit", status_code=201)
async def submit_widget_form(fid: str, body: FormSubmit,
                                request: Request,
                                background_tasks: BackgroundTasks,
                                tenant: Dict[str, Any] = Depends(require_widget_auth)):
    form = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"], "active": {"$ne": False}},
        {"_id": 0},
    )
    if not form:
        raise HTTPException(404, "Form not found or not active")

    # Turnstile — verify or graceful bypass.
    client_ip = None
    if request.client:
        client_ip = request.client.host
    await _verify_turnstile(body.turnstile_token, client_ip)

    # GH-Fix: normalise ``answers`` / ``data`` into a single mapping.
    # ``answers`` wins when both are supplied.
    payload = body.answers if body.answers is not None else body.data
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "answers/data must be an object")

    # TD-53 · Feb-2026 — Phase 2 ``show_if`` conditional-logic. Build
    # the field-by-id map once so the visibility evaluator can resolve
    # parent references, then strip hidden-field values from the
    # payload BEFORE required-check + lead extraction. This gives:
    #   * Hidden fields marked ``required=True`` do NOT trigger a 422.
    #   * Hidden fields' answers do NOT get pulled into the lead row
    #     (``extract_contact_fields_with_schema`` only sees visible
    #     answers).
    # Legacy forms (no ``show_if`` on any field) retain byte-identical
    # behavior: ``_is_field_visible`` short-circuits to True on
    # None-rule fields; the ``[]`` loop produces an empty hidden-fid
    # set; nothing is stripped.
    _fields_list = form.get("fields") or []
    _fields_by_id = {
        f["id"]: f for f in _fields_list if isinstance(f, dict) and f.get("id")
    }
    _hidden_fids: set = set()
    for f in _fields_list:
        if not isinstance(f, dict):
            continue
        if not _is_field_visible(f, payload, _fields_by_id):
            _hidden_fids.add(f.get("id"))
            # Strip the field's value from the payload under BOTH
            # name + id keys so neither the required-check nor the
            # schema-aware extractor can see it. The original payload
            # is NOT persisted here (payload is a Python-level mutation
            # of the submitted body); the sub_doc below will store the
            # post-strip view, which is the operator-visible truth —
            # hidden fields should not persist their stale values.
            if f.get("name"):
                payload.pop(f["name"], None)
            if f.get("id"):
                payload.pop(f["id"], None)

    # Required-field validation.
    missing: List[str] = []
    for f in form.get("fields") or []:
        if not f.get("required"):
            continue
        # Skip required-check on hidden fields (TD-53).
        if f.get("id") in _hidden_fids:
            continue
        # Accept the value under either the field's ``name`` or ``id``.
        val = payload.get(f["name"])
        if val is None and f.get("id"):
            val = payload.get(f["id"])
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(f["name"])
    if missing:
        raise HTTPException(
            422, f"missing required fields: {', '.join(missing)}"
        )

    # TD-52 · Feb-2026 — per-type submission sanity for the new
    # palette entries. Enforced AFTER the required-check so a
    # missing-value error still wins (clearer operator UX).
    _validate_td52_field_values(form.get("fields") or [], payload)

    # Persist submission.
    sub_id = new_id()
    sub_doc = {
        "id": sub_id,
        "tenant_id": tenant["id"],
        "form_id": fid,
        "form_slug": form.get("slug"),
        "form_name": form.get("name"),
        "answers": payload,
        # Legacy mirror to keep the pre-fix consumers reading ``data``.
        "data": payload,
        "page_url": body.page_url,
        "ip": client_ip,
        "user_agent": request.headers.get("user-agent"),
        "created_at": now_iso(),
    }
    await db.form_submissions.insert_one(sub_doc)

    # Contact extraction from submitted answers — shared with the
    # legacy public-form path via ``services/lead_extraction``.
    #
    # Phase L2.5 · Feb-2026 — schema-aware wire-in.  Modern widget
    # forms author fields with auto-generated ids (``field_9`` /
    # ``field_Service Address_5``); the pre-L2 helper only matches on
    # ``id`` / ``name`` and silently drops those values.  The
    # ``_with_schema`` variant runs the pre-L2 key path first (so
    # exact key hits still win) then falls back to label matching
    # against the form's ``fields`` array.  Anti-match rules in
    # ``lead_extraction._LABEL_ANTI_MATCH`` prevent a "Service
    # Address" label from stomping ``service_interest`` and vice
    # versa.
    from services.lead_extraction import extract_contact_fields_with_schema
    _schema_fields = form.get("fields") or []
    _extracted = extract_contact_fields_with_schema(payload, _schema_fields)
    name = _extracted["name"]
    email = _extracted["email"]
    phone = _extracted["phone"]
    notes = _extracted["message"]
    address = _extracted["address"]
    service_interest = _extracted["service_interest"]

    # ── Post-submit orchestration ────────────────────────────────────
    submit_cfg = form.get("submit_config") or {}
    creates = (submit_cfg.get("creates") or "lead").lower()
    lead_id: Optional[str] = None
    customer_id: Optional[str] = None

    if creates in ("lead", "both") and (email or phone):
        lead_id = await _upsert_lead_from_submission(
            tenant_id=tenant["id"], form=form, submission_id=sub_id,
            name=name, email=email, phone=phone, notes=notes,
            address=address, service_interest=service_interest,
            first_name=_extracted["first_name"],
            last_name=_extracted["last_name"],
            city=_extracted["city"],
            state=_extracted["state"],
            zip=_extracted["zip"],
            company_name=_extracted["company_name"],
            page_url=body.page_url,
        )
        # Feb-2026 · P18 — dispatch tenant-configured lead alerts to
        # the SMS+email recipient lists when the upsert path created a
        # brand-new lead row (existing-lead reuse skips the fan-out
        # since the tenant already knows).
        _created = getattr(_upsert_lead_from_submission,
                              "_last_created", None)
        if _created and _created.get("lead", {}).get("id") == lead_id:
            try:
                from services.lead_notifications import send_lead_alert_notifications
                await send_lead_alert_notifications(
                    lead=_created["lead"], tenant=tenant,
                    background_tasks=background_tasks,
                )
            except Exception as _e:  # noqa: BLE001
                logger.warning(f"[p18] lead alert dispatch failed: {_e}")
            # Feb-2026 · Admin lead-notification fan-out (widget-form
            # ingress). Same rationale as the ``/api/public/leads``
            # hook — reach every admin/manager user +
            # business_settings.notification_email regardless of
            # whether the tenant has configured the K63 rich list.
            try:
                from services.lead_admin_notifications import (
                    dispatch_admin_lead_email,
                )
                await dispatch_admin_lead_email(
                    lead=_created["lead"], tenant=tenant,
                    background_tasks=background_tasks,
                )
            except Exception as _e:  # noqa: BLE001
                logger.warning(
                    f"[lead-admin-fanout] widget-form dispatch failed: {_e}"
                )
            # Reset so a duplicate call in the same request doesn't re-fire.
            _upsert_lead_from_submission._last_created = None      # type: ignore[attr-defined]
    if creates in ("customer", "both") and (email or phone):
        customer_id = await _upsert_customer_from_submission(
            tenant_id=tenant["id"],
            name=name, email=email, phone=phone,
            address=address, notes=notes,
        )

    # TD-51 · Feb-2026 — three new single-value destinations.  Mutually
    # exclusive with ``lead`` / ``customer`` / ``both`` by the enum
    # validator on ``SubmitConfig``, so these branches are only
    # reached when the author explicitly selected one.  Each helper
    # is tenant-scoped + idempotency-free (brand-new row per submit),
    # and is wrapped in a try/except so a downstream insert failure
    # does NOT 500 the public widget submit path — the submission row
    # is already persisted, and the cross-ref will be null on failure
    # for operator follow-up.
    job_request_id: Optional[str] = None
    service_report_id: Optional[str] = None
    quote_request_id: Optional[str] = None

    if creates == "booking":
        try:
            job_request_id = await _create_job_request_from_submission(
                tenant_id=tenant["id"], form=form, submission_id=sub_id,
                name=name, email=email, phone=phone, address=address,
                notes=notes, service_interest=service_interest,
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning("[td51-booking] insert failed: %s", _e)

    if creates == "service_log":
        try:
            service_report_id = await _create_service_log_from_submission(
                tenant_id=tenant["id"], form=form, submission_id=sub_id,
                name=name, email=email, phone=phone, address=address,
                notes=notes,
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning("[td51-service_log] insert failed: %s", _e)

    if creates == "quote_request":
        try:
            quote_request_id = await _create_quote_request_from_submission(
                tenant_id=tenant["id"], form=form, submission_id=sub_id,
                name=name, email=email, phone=phone, address=address,
                notes=notes, service_interest=service_interest,
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning("[td51-quote_request] insert failed: %s", _e)

    subject_kind, subject_id = _pick_subject(
        creates, lead_id, customer_id,
        job_request_id=job_request_id,
        service_report_id=service_report_id,
        quote_request_id=quote_request_id,
    )

    # Confirmation email — mocked delivery reusing the M5/M6 pipeline.
    delivery_id: Optional[str] = None
    if submit_cfg.get("confirmation_email_template_id") and email:
        delivery_id = await _queue_confirmation_email(
            tenant_id=tenant["id"],
            template_id=submit_cfg["confirmation_email_template_id"],
            payload=payload, form=form, submission_id=sub_id,
            recipient_email=email, recipient_name=name,
            subject_kind=subject_kind, subject_id=subject_id,
        )

    # Drip enrolment (M5) — one active enrolment per subject per sequence.
    # TD-51 · Drip is intentionally skipped for the three new ``creates``
    # kinds (booking / service_log / quote_request) — those are
    # operational triage entries, not marketing cadence subjects.
    # Enforced here via ``subject_kind in _DRIP_SUBJECT_KINDS`` so a
    # future contract change on ``_enrol_in_sequence`` doesn't silently
    # start enrolling job-requests.
    enrolment_id: Optional[str] = None
    if (submit_cfg.get("drip_sequence_id") and subject_id
            and subject_kind in _DRIP_SUBJECT_KINDS):
        enrolment_id = await _enrol_in_sequence(
            tenant_id=tenant["id"],
            sequence_id=submit_cfg["drip_sequence_id"],
            subject_kind=subject_kind, subject_id=subject_id,
            source_ref={"form_id": fid, "submission_id": sub_id},
        )

    # Admin bell — the canonical flag lives on ``submit_config`` now;
    # fall back to the legacy top-level ``notify_admin_bell`` for
    # backwards-compat with any pre-GH-fix rows.
    admin_bell = submit_cfg.get(
        "admin_bell",
        form.get("notify_admin_bell", True),
    )
    if admin_bell:
        try:
            from services.notifications import enqueue_for_tenant_admins
            display = name or email or phone or "Anonymous"
            # TD-51 · Pick the richest available href for operator
            # triage. Priority: lead → customer → job_request →
            # service_report → quote_request → forms list.
            if lead_id:
                _href = f"/leads/{lead_id}"
            elif customer_id:
                _href = f"/customers/{customer_id}"
            elif job_request_id:
                _href = f"/admin/job-requests?id={job_request_id}"
            elif service_report_id:
                _href = f"/admin/service-reports/{service_report_id}"
            elif quote_request_id:
                _href = f"/admin/lead-requests/{quote_request_id}"
            else:
                _href = "/marketing/forms"
            await enqueue_for_tenant_admins(
                tenant["id"],
                kind="form_submission",
                title=f"Form submission — {form.get('name') or form.get('slug')}",
                body=f"From {display}",
                source_ref={
                    "kind": "form_submission",
                    "form_id": fid,
                    "submission_id": sub_id,
                    "lead_id": lead_id,
                    "customer_id": customer_id,
                    "job_request_id": job_request_id,
                    "service_report_id": service_report_id,
                    "quote_request_id": quote_request_id,
                },
                href=_href,
                priority="normal",
            )
        except Exception as exc:  # pragma: no cover — logged only
            logger.warning("[h1] admin bell fan-out failed: %s", exc)

    # Persist cross-refs onto the submission + bump form counter.
    await db.form_submissions.update_one(
        {"id": sub_id},
        {"$set": {
            "lead_id": lead_id,
            "customer_id": customer_id,
            "delivery_id": delivery_id,
            "enrolment_id": enrolment_id,
            # TD-51 · Feb-2026 — new cross-refs. Always written
            # (null when the branch didn't run) so operator audit
            # queries can filter by presence/absence.
            "job_request_id": job_request_id,
            "service_report_id": service_report_id,
            "quote_request_id": quote_request_id,
        }},
    )
    await db.marketing_forms.update_one(
        {"id": fid, "tenant_id": tenant["id"]},
        {"$inc": {"submission_count": 1},
         "$set": {"updated_at": now_iso()}},
    )

    return {
        "ok": True,
        "submission_id": sub_id,
        "lead_id": lead_id,
        "customer_id": customer_id,
        "delivery_id": delivery_id,
        "enrolment_id": enrolment_id,
        # TD-51 · Feb-2026 — surface the three new cross-refs on the
        # public widget response so clients can route the post-submit
        # confirmation screen if they want to.
        "job_request_id": job_request_id,
        "service_report_id": service_report_id,
        "quote_request_id": quote_request_id,
        "success_message": form.get("success_message"),
    }


# ─── Post-submit helpers ──────────────────────────────────────────────

def _pick_subject(creates: str,
                    lead_id: Optional[str],
                    customer_id: Optional[str],
                    *,
                    job_request_id: Optional[str] = None,
                    service_report_id: Optional[str] = None,
                    quote_request_id: Optional[str] = None) -> tuple:
    """Choose which entity a downstream action (email, drip) is bound
    to. Preference: explicit ``customer`` > ``both``-then-customer >
    fallback ``lead``.

    TD-51 · Feb-2026 — new ``creates`` kinds carry a non-``lead``/
    ``customer`` ``subject_kind`` so the drip-enrolment gate can
    recognise them and skip; ``_queue_confirmation_email`` is
    agnostic and reuses the kind as a tag only.  Drip subject
    kinds that aren't in ``_DRIP_SUBJECT_KINDS`` must therefore
    NEVER reach ``_enrol_in_sequence``.
    """
    if creates in ("customer", "both") and customer_id:
        return "customer", customer_id
    if creates == "booking" and job_request_id:
        return "job_request", job_request_id
    if creates == "service_log" and service_report_id:
        return "service_report", service_report_id
    if creates == "quote_request" and quote_request_id:
        return "quote_request", quote_request_id
    if lead_id:
        return "lead", lead_id
    if customer_id:
        return "customer", customer_id
    return "lead", None


# ─── TD-51 downstream helpers ────────────────────────────────────────
#
# Each helper inserts ONE new row into its target collection with:
#   * Tenant-scoped ``tenant_id``.
#   * ``source="marketing_form"`` + ``source_ref`` back to the
#     submission (so operator UIs can audit the ingress path).
#   * No idempotency / dedup — each submit is a brand-new row.  If
#     operators later want dedup, they can add it per-destination
#     without touching the dispatcher.
#   * Deliberately NOT fanning out downstream notifications
#     (``notify_emit`` on job_requests, email-send on lead_requests)
#     — the form-submission admin bell already fires; firing twice
#     would be duplicative noise.
# ────────────────────────────────────────────────────────────────────


async def _create_job_request_from_submission(
    *, tenant_id: str, form: Dict[str, Any], submission_id: str,
    name: Optional[str], email: Optional[str], phone: Optional[str],
    address: Optional[str], notes: Optional[str],
    service_interest: Optional[str],
) -> str:
    """TD-51 · ``creates="booking"`` → ``db.job_requests`` queue row.

    Minimum shape: carries the public contact info + the form hint
    into the operator-triage queue defined by ``routers/job_requests``.
    ``status="pending"`` matches that router's lifecycle so the row
    surfaces in the existing admin review UI.
    """
    rid = new_id()
    doc = {
        "id": rid,
        "tenant_id": tenant_id,
        "customer_id": None,
        "customer_name_hint": name or "",
        "customer_phone_hint": phone or "",
        "address_hint": address or "",
        "service_type": service_interest or "",
        "scheduled_preference": "asap",
        "priority": "normal",
        "notes": (notes or "")[:1000],
        "photos": [],
        "requested_by_user_id": None,
        "requested_by_name": name or email or phone or "Public form",
        "status": "pending",
        "created_at": now_iso(),
        "reviewed_at": None,
        "reviewed_by_user_id": None,
        "converted_job_id": None,
        "rejection_reason": None,
        # TD-51 markers.
        "source": "marketing_form",
        "source_ref": {
            "kind": "form_submission",
            "form_id": form.get("id"),
            "submission_id": submission_id,
            "contact_email": email or "",
            "contact_phone": phone or "",
        },
    }
    await db.job_requests.insert_one(doc)
    return rid


async def _create_service_log_from_submission(
    *, tenant_id: str, form: Dict[str, Any], submission_id: str,
    name: Optional[str], email: Optional[str], phone: Optional[str],
    address: Optional[str], notes: Optional[str],
) -> str:
    """TD-51 · ``creates="service_log"`` → ``db.service_reports`` row.

    Caveat: ``service_reports`` is the live tech post-service
    reporting collection (schema shared with the tech dashboard).
    To avoid shape pollution, the row is seeded with:
      * ``tech_id = None`` so tech-filtered dashboards exclude it.
      * ``job_id = None`` so job-pivot queries ignore it.
      * ``template = "marketing_form_submission"`` so UI can
        distinguish the ingress path.
      * Empty chemistry / checklist arrays (schema-valid shape).
      * ``source = "marketing_form"`` + ``source_ref`` for audit.
    """
    rid = new_id()
    _now = now_iso()
    doc = {
        "id": rid,
        "tenant_id": tenant_id,
        "job_id": None,
        "tech_id": None,
        "template": "marketing_form_submission",
        "chemical_readings": [],
        "chemicals_added": [],
        "checklist_items": [],
        "not_tested_flags": {},
        "notes": (notes or "")[:2000],
        "photos": [],
        "water_bodies": [],
        "started_at": _now,
        "submitted_at": _now,
        "created_at": _now,
        "updated_at": _now,
        # TD-51 markers + contact capture.
        "source": "marketing_form",
        "customer_name_hint": name or "",
        "customer_email_hint": email or "",
        "customer_phone_hint": phone or "",
        "address_hint": address or "",
        "source_ref": {
            "kind": "form_submission",
            "form_id": form.get("id"),
            "submission_id": submission_id,
        },
    }
    await db.service_reports.insert_one(doc)
    return rid


async def _create_quote_request_from_submission(
    *, tenant_id: str, form: Dict[str, Any], submission_id: str,
    name: Optional[str], email: Optional[str], phone: Optional[str],
    address: Optional[str], notes: Optional[str],
    service_interest: Optional[str],
) -> str:
    """TD-51 · ``creates="quote_request"`` → ``db.lead_requests`` row.

    NOTE: distinct from the ``db.lead_request_dispatches`` collection
    used by ``routers/lead_requests.py`` (the admin-initiated
    dispatch flow). Those docs have a ``generated_token`` +
    ``admin_id`` lifecycle; TD-51 writes into the sibling
    ``db.lead_requests`` collection which was previously empty.
    """
    rid = new_id()
    doc = {
        "id": rid,
        "tenant_id": tenant_id,
        "kind": "quote_request",
        "status": "new",
        "name": name or "",
        "email": email or "",
        "phone": phone or "",
        "address": address or "",
        "service_interest": service_interest or "",
        "notes": (notes or "")[:2000],
        "created_at": now_iso(),
        # TD-51 markers.
        "source": "marketing_form",
        "source_ref": {
            "kind": "form_submission",
            "form_id": form.get("id"),
            "submission_id": submission_id,
        },
    }
    await db.lead_requests.insert_one(doc)
    return rid


async def _upsert_lead_from_submission(
    *, tenant_id: str, form: Dict[str, Any], submission_id: str,
    name: Optional[str], email: Optional[str], phone: Optional[str],
    notes: Optional[str], page_url: Optional[str],
    address: Optional[str] = None,
    service_interest: Optional[str] = None,
    # ── Phase F5 · Feb-2026 — expanded schema fields.  All optional
    #     so callers that pre-date F5 keep working.
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip: Optional[str] = None,        # noqa: A002 — matches lead-doc key
    company_name: Optional[str] = None,
) -> Optional[str]:
    if not (email or phone):
        return None
    existing = None
    if email:
        existing = await db.leads.find_one(
            {"tenant_id": tenant_id, "email": email},
            {"_id": 0, "id": 1},
        )
    if not existing and phone:
        existing = await db.leads.find_one(
            {"tenant_id": tenant_id, "phone": phone},
            {"_id": 0, "id": 1},
        )
    if existing:
        return existing["id"]
    lead_id = new_id()
    lead_doc = {
        "id": lead_id,
        "tenant_id": tenant_id,
        "name": name or "Form visitor",
        "email": email or "",
        "phone": phone or "",
        # Feb-2026 · Widget lead persistence parity — mirror the legacy
        # ``_lead_row_from_form_values`` shape so both list + detail
        # surfaces render the address without a special-case fallback.
        "address": address or "",
        "service_address": address or "",
        "service_interest": service_interest,
        # ── Phase F5 fields ─────────────────────────────────────
        "first_name": first_name or "",
        "last_name": last_name or "",
        "city": city or "",
        "state": state or "",
        "zip": zip or "",
        "company_name": company_name or "",
        "source": f"form:{form.get('slug') or form.get('id')}",
        "status": "new",
        "notes": (notes or "")[:500],
        "message": notes or "",
        "meta": {"form_id": form.get("id"),
                 "submission_id": submission_id,
                 "page_url": page_url},
        "created_at": now_iso(),
    }
    await db.leads.insert_one(lead_doc)
    # Feb-2026 · P18 — expose the created lead + tenant on the
    # module-level context so the outer widget-form endpoint can
    # dispatch the P18 SMS+email alert to tenant-configured
    # recipients.  Piggybacks on the return signature to avoid
    # threading BackgroundTasks through every helper.
    _upsert_lead_from_submission._last_created = {          # type: ignore[attr-defined]
        "lead": lead_doc, "tenant_id": tenant_id,
    }
    return lead_id


async def _upsert_customer_from_submission(
    *, tenant_id: str, name: Optional[str], email: Optional[str],
    phone: Optional[str], address: Optional[str], notes: Optional[str],
) -> Optional[str]:
    if not (email or phone):
        return None
    existing = None
    if email:
        existing = await db.customers.find_one(
            {"tenant_id": tenant_id, "email": email},
            {"_id": 0, "id": 1},
        )
    if not existing and phone:
        existing = await db.customers.find_one(
            {"tenant_id": tenant_id, "phone": phone},
            {"_id": 0, "id": 1},
        )
    if existing:
        return existing["id"]
    cust_id = new_id()
    await db.customers.insert_one({
        "id": cust_id,
        "tenant_id": tenant_id,
        "name": name or "Form visitor",
        "email": email or "",
        "phone": phone or "",
        "address": address or "",
        "notes": (notes or "")[:500],
        "source": "form_submission",
        "created_at": now_iso(),
    })
    return cust_id


async def _queue_confirmation_email(
    *, tenant_id: str, template_id: str,
    payload: Dict[str, Any], form: Dict[str, Any], submission_id: str,
    recipient_email: str, recipient_name: Optional[str],
    subject_kind: str, subject_id: Optional[str],
) -> Optional[str]:
    """Render the M3 template against the submission answers + drop a
    mock delivery row into ``marketing_deliveries``. Matches the same
    contract M5/M6 already writes so the analytics dashboard picks it
    up for free."""
    tpl = await db.marketing_templates.find_one(
        {"id": template_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not tpl:
        logger.warning("[h1] confirmation template %s vanished", template_id)
        return None
    try:
        from services.marketing.render import render_subject_and_body
        ctx = {
            "customer": {"name": recipient_name or "there",
                          "email": recipient_email},
            "form": {"name": form.get("name"), "slug": form.get("slug")},
            "answers": payload,
        }
        subject, body_rendered, _missing = render_subject_and_body(
            (tpl.get("subject") or ""), (tpl.get("body") or ""), ctx,
        )
    except Exception as exc:
        logger.warning("[h1] template render failed: %s", exc)
        subject = tpl.get("subject") or "Thanks for your submission"
        body_rendered = tpl.get("body") or ""

    delivery_id = new_id()
    # Slice N broadening · route the confirmation through the Resend
    # adapter with category=transactional (confirmations bypass
    # marketing suppression).
    provider = "mock"
    provider_status = None
    provider_response_id = None
    attempts = 0
    try:
        from services.email.resend_adapter import send as _resend_send
        res = await _resend_send(
            to=recipient_email,
            subject=subject,
            html=body_rendered,
            category="transactional",
            tenant_id=tenant_id,
            customer_id=(subject_id if subject_kind == "customer" else None),
            idempotency_key=f"h1:{submission_id}",
        )
        provider = res.get("provider") or "mock"
        provider_status = res.get("provider_status")
        provider_response_id = res.get("provider_response_id")
        attempts = res.get("attempts") or 0
    except Exception as exc:  # pragma: no cover
        logger.warning("[h1] resend adapter failed: %s", exc)
        provider_status = "failed"

    await db.marketing_deliveries.insert_one({
        "id": delivery_id,
        "tenant_id": tenant_id,
        "sequence_id": None,
        "enrolment_id": None,
        "form_id": form.get("id"),
        "form_submission_id": submission_id,
        "step_index": 0,
        "customer_id": subject_id if subject_kind == "customer" else None,
        "lead_id": subject_id if subject_kind == "lead" else None,
        "channel": "email",
        "template_id": template_id,
        "subject_rendered": subject,
        "body_rendered": body_rendered,
        "recipient_email": recipient_email,
        "mock": provider == "mock",
        "provider": provider,
        "provider_status": provider_status,
        "provider_response_id": provider_response_id,
        "attempts": attempts,
        "sent_at": now_iso(),
        "provider_response_stub": {"ok": True, "id": f"mock-{delivery_id[:8]}"},
    })
    return delivery_id


async def _enrol_in_sequence(
    *, tenant_id: str, sequence_id: str,
    subject_kind: str, subject_id: str,
    source_ref: Dict[str, Any],
) -> Optional[str]:
    """Insert a ``marketing_drip_enrolments`` row. Uses the M5 shape
    (customer_id + status=active) so the existing sequence-tick worker
    picks it up. When the subject is a Lead we still populate
    ``customer_id`` (with the lead's id) so the tick worker keys on it
    uniformly, and set ``subject_kind`` for downstream disambiguation."""
    seq = await db.marketing_sequences.find_one(
        {"id": sequence_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not seq:
        logger.warning("[h1] drip sequence %s vanished", sequence_id)
        return None
    # Skip if an active enrolment already exists for this subject.
    dup = await db.marketing_drip_enrolments.find_one(
        {"tenant_id": tenant_id, "sequence_id": sequence_id,
         "customer_id": subject_id, "status": "active"},
        {"_id": 0, "id": 1},
    )
    if dup:
        return dup["id"]
    first_delay = 0
    if seq.get("steps"):
        first_delay = int(seq["steps"][0].get("delay_hours") or 0)
    next_at = (datetime.now(timezone.utc)
                + timedelta(hours=first_delay)).isoformat()
    eid = new_id()
    await db.marketing_drip_enrolments.insert_one({
        "id": eid, "tenant_id": tenant_id,
        "sequence_id": sequence_id,
        "customer_id": subject_id,
        "subject_kind": subject_kind,
        "trigger_source": "form_submission",
        "source_ref": source_ref,
        "enrolled_at": now_iso(),
        "current_step": 0,
        "next_send_at": next_at if seq.get("steps") else None,
        "status": "active" if seq.get("steps") else "completed",
        "halt_reason": None,
        "history": [],
    })
    return eid


def _first_str(d: Dict[str, Any], keys: List[str]) -> Optional[str]:
    # Phase F5 · Feb-2026 — kept for local uses (Slice L.b multipart
    # path only). Delegates to the shared helper so alias + whitespace
    # behaviour stays consistent across both intake paths.
    from services.lead_extraction import first_str as _shared_first_str
    return _shared_first_str(d, keys)


# ══════════════════════════════════════════════════════════════════════
# Slice L.b · Multipart submit — files land in Object Storage.
# ══════════════════════════════════════════════════════════════════════
_MAX_FILE_BYTES = 10 * 1024 * 1024    # 10 MB per file
_MAX_TOTAL_BYTES = 30 * 1024 * 1024   # 30 MB aggregate per submission


@router.post("/widget/form/{fid}/submit-multipart", status_code=201)
async def submit_widget_form_multipart(
    fid: str,
    request: Request,
    answers: str = Form("{}"),   # JSON-encoded blob of the non-file answers
    turnstile_token: Optional[str] = Form(None),
    page_url: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    tenant: Dict[str, Any] = Depends(require_widget_auth),
):
    """Multipart variant of :func:`submit_widget_form`.  Accepts the
    non-file answers under a JSON blob (``answers``) + zero or more
    file uploads which are streamed to the Emergent Object Storage
    bucket.  Each upload is recorded under ``file_uploads`` on the
    submission doc with ``{field_name, url, filename, size_bytes}``.

    Caps: 10 MB per file, 30 MB aggregate.  Requests that exceed either
    cap return 413 before touching storage."""
    import json
    form = await db.marketing_forms.find_one(
        {"id": fid, "tenant_id": tenant["id"], "active": {"$ne": False}},
        {"_id": 0},
    )
    if not form:
        raise HTTPException(404, "Form not found or not active")

    client_ip = request.client.host if request.client else None
    await _verify_turnstile(turnstile_token, client_ip)

    try:
        payload = json.loads(answers or "{}")
    except json.JSONDecodeError:
        raise HTTPException(422, "answers must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(422, "answers must be an object")

    # Read + validate file uploads before touching storage.
    file_records: List[Dict[str, Any]] = []
    total = 0
    for f in files:
        data = await f.read()
        size = len(data)
        if size > _MAX_FILE_BYTES:
            raise HTTPException(413, f"file {f.filename} exceeds 10MB limit")
        total += size
        if total > _MAX_TOTAL_BYTES:
            raise HTTPException(413, "aggregate upload exceeds 30MB limit")
        file_records.append({
            "field_name": f.filename or "attachment",
            "filename": f.filename or "attachment",
            "content_type": f.content_type or "application/octet-stream",
            "size_bytes": size,
            "_bytes": data,
        })

    # Stream to Object Storage.  Import lazily so environments without
    # the SDK (early dev) can still submit forms — those uploads land as
    # local-only metadata rows.
    uploaded: List[Dict[str, Any]] = []
    try:
        from emergentintegrations.storage.object_storage import EmergentObjectStorage
        storage = EmergentObjectStorage()
        for rec in file_records:
            key = f"tenants/{tenant['id']}/form-uploads/{new_id()}/{rec['filename']}"
            url = storage.upload_file(
                bucket_name="form-uploads",
                key=key, data=rec["_bytes"],
                content_type=rec["content_type"],
            )
            uploaded.append({
                "field_name": rec["field_name"],
                "filename": rec["filename"],
                "content_type": rec["content_type"],
                "size_bytes": rec["size_bytes"],
                "url": url,
                "storage_key": key,
            })
    except Exception as exc:
        logger.warning("[l.b] object storage upload failed, keeping metadata: %s", exc)
        for rec in file_records:
            uploaded.append({
                "field_name": rec["field_name"],
                "filename": rec["filename"],
                "content_type": rec["content_type"],
                "size_bytes": rec["size_bytes"],
                "url": None, "storage_key": None,
                "upload_error": str(exc)[:200],
            })

    # Persist submission with file metadata.
    sub_id = new_id()
    sub_doc = {
        "id": sub_id, "tenant_id": tenant["id"],
        "form_id": fid, "form_slug": form.get("slug"),
        "form_name": form.get("name"),
        "answers": payload, "data": payload,
        "file_uploads": uploaded,
        "page_url": page_url, "ip": client_ip,
        "user_agent": request.headers.get("user-agent"),
        "submission_kind": "multipart",
        "created_at": now_iso(),
    }
    await db.form_submissions.insert_one(sub_doc)
    return {"submission_id": sub_id,
             "file_count": len(uploaded),
             "total_bytes": sum(u["size_bytes"] for u in uploaded)}
