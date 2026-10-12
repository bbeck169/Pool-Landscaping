from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator, AliasChoices
from typing import List, Literal, Optional, Any, Dict
from datetime import datetime
import re


def validate_password_strength(v: str) -> str:
    """Password policy for SOC2/ISO 27001 technical controls."""
    if v is None or len(v) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain an uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain a lowercase letter")
    if not re.search(r"[0-9]", v):
        raise ValueError("Password must contain a number")
    return v


class LoginRequest(BaseModel):
    # 2026-10-02 followup · see memory/PORTAL_EDIT_PROFILE_FOLLOWUPS.md §1.
    # ``email: EmailStr`` previously rejected RFC 2606 reserved TLDs
    # (.local / .test / .example) via email-validator's
    # ``check_deliverability`` policy, but
    # ``PATCH /customer-portal/profile`` accepts them via the lenient
    # regex at ``routers/customer_portal.py::_valid_email``. The
    # asymmetry locked customers out when their stored primary email
    # landed on a reserved TLD (home-lab / dev-loopback workflows).
    # Widened to ``str`` + an inline regex mirroring ``_valid_email`` so
    # both paths agree. Still rejects obviously malformed inputs
    # (missing @, missing TLD, whitespace).
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email_lenient_format(cls, v: str) -> str:
        v = (v or "").strip()
        # Mirrors routers/customer_portal.py::_valid_email (2026-10-02).
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("value is not a valid email address")
        return v


class CustomerIn(BaseModel):
    name: str
    # Phase 56.3.A — split first/last names. Both are optional at the API
    # boundary so legacy clients that only send `name` keep working; the
    # router auto-splits `name` on the first space when first/last are
    # absent, and re-composes `name` when first+last are provided.
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    # Phase 48 · Feb-2026 — dedicated landline field. Separate from
    # ``phone`` (which is the primary SMS/voice mobile) and from the
    # ``mobiles[]`` array (which holds additional mobile lines). Legacy
    # customer docs without the field read back as empty string.
    home_phone: Optional[str] = ""
    address: Optional[str] = ""
    # 2026-02 · P0 Stage 3 Commit D — the city/state/zip/postal_code/
    # country fields were previously undeclared, so Pydantic's default
    # ``extra="ignore"`` posture SILENTLY DROPPED them from the stored
    # customer doc. The preview-isolation sanitizer sets them to the
    # synth sentinel (Testville/AZ/85000/US) but those values never
    # survived the ``CustomerIn.dict()`` round-trip. Declare the fields
    # here so POST → GET round-trip preserves them. ``postal_code``
    # mirrors ``zip`` for international callers; routers that need to
    # pick one authoritative value should prefer ``postal_code`` when
    # both are present (the sanitizer sets them identically).
    city: Optional[str] = ""
    state: Optional[str] = ""
    zip: Optional[str] = ""
    postal_code: Optional[str] = ""
    country: Optional[str] = ""
    # ``custom_fields`` — arbitrary key/value admin notes (gate codes,
    # pool quirks, etc.). The decorator preserves the KEY structure
    # and recursively redacts string VALUES on preview env (pasted-in
    # emails / phones get the free-text redact pass). Same
    # pre-Commit-D field-drop story: the field has to be declared or
    # Pydantic strips it.
    custom_fields: Optional[Dict[str, Any]] = None
    billing_address: Optional[str] = ""
    gate_code: Optional[str] = ""
    notes: Optional[str] = ""
    avatar: Optional[str] = ""
    # Phase 2 additions:
    tags: Optional[List[str]] = []           # e.g. ["VIP", "Specialty"] plus arbitrary custom tags
    # APR-II · Feb-2026 — removed ``alert_email`` + ``alert_phone``
    # (after-hours escalation channels).  Zero divergent rows in DB
    # at removal time; recap SMS routing collapsed to
    # ``customer.phone`` only.  See
    # ``service_reports.py::_send_recap_sms`` for the fallback
    # simplification.
    waitlisted: Optional[bool] = False       # unscheduled customer flagged as waiting for a slot
    secondary_addresses: Optional[List[str]] = []
    # Phase 34d — pool volume in US gallons. Feeds Phase 34e chemical dosing.
    # Optional; existing customer docs read back as null. When provided,
    # must be a plain integer between 1 and 500,000 gallons.
    pool_gallons: Optional[int] = None
    # Phase 34d-follow — VIP flag. Surfaces a gold badge on the customer
    # header and on every schedule/dispatch card that references this
    # customer. Existing docs without the field read back as False on the
    # client (JSON `undefined` is falsy in both React and RN).
    is_vip: Optional[bool] = False
    # Feb-2026 Customer Detail Additions — VIP metadata. ``vip_since``
    # is auto-stamped when ``is_vip`` flips to True and cleared when it
    # flips back to False (see routers/customers.py::_apply_vip_stamp).
    vip_since: Optional[str] = None
    vip_note: Optional[str] = None
    # Feb-2026 service-notes ship — two long-form notes per customer,
    # surfaced on the schedule view based on the assigned tech's
    # specialty or the job's ``service_type`` field. Admin-editable
    # only; techs see the note matching their service focus. ``None``
    # values render as empty placeholder cards.
    service_notes: Optional[Dict[str, Optional[str]]] = None
    # Feb-2026 MP1 — Multi-property support. Master billing mode
    # controls how invoices roll up across the customer's properties:
    #   * off (default) — each property invoices independently
    #   * consolidated — line items combine into one customer invoice
    #   * forward_to_master_contact — separate invoices, one recipient
    # See routers/properties.py::resolve_invoice_recipient for the
    # routing logic every invoice send path plugs into.
    master_billing_mode: Optional[str] = "off"
    master_billing_contact_email: Optional[str] = None
    master_billing_contact_phone: Optional[str] = None
    # Feb-2026 Customer Detail Additions — multi-contact arrays.
    # Up to 4 mobiles / 4 emails per customer (Phase-1 bump 3→4;
    # cap constants live in services.customer_multi_contact as
    # ``MAX_MOBILES`` / ``MAX_EMAILS``). Each entry carries a label,
    # is_primary flag, and marketing/sms consent flag. The legacy
    # scalar ``phone`` / ``email`` fields are auto-synced to the
    # primary entry on every write via services.customer_multi_contact.
    mobiles: Optional[List[dict]] = None
    emails: Optional[List[dict]] = None
    # Phase 34f — Active/inactive lifecycle. Defaults to True; when an admin
    # flips this to False via PUT /api/customers/{id}, the router cascades a
    # cancellation over all future scheduled jobs and deactivates recurring
    # templates. Missing/legacy docs read back as True (assumed active).
    # Phase 33 Step B · Feb-2026 — PDF-import auto-create provenance.
    # ``source`` tags the origin channel of the customer row
    # (``"pdf_import"`` for rows minted by the PDF-import
    # auto-create helper, otherwise empty for operator-created or
    # legacy rows). ``created_via`` carries a finer-grained method
    # token (``"pdf_import_auto"`` for the auto-create path).
    # Downstream readers (audit, Customer Detail badge, admin
    # review UI) key off these to distinguish auto-created
    # customers from operator-created ones. Legacy customers
    # without the fields read back as empty string.
    source: Optional[str] = ""
    created_via: Optional[str] = ""
    # Phase 55-a · Aug-2026 — Homeworks importer FK. Nullable; set by
    # the Copilot CRM importer so a single ``rollback`` on the batch
    # can ``delete_many({import_batch_id: X})``. Legacy customers read
    # back as ``None``.
    import_batch_id: Optional[str] = None
    is_active: Optional[bool] = True
    # Feb-2026 · P42 — auto-populated by the lifecycle helper when the
    # customer crosses the "converted" threshold (active + ≥1 job).
    # Read-only in practice — API surfaces it back but any write is
    # ignored by the router paths (immutable once set). Kept Optional
    # so legacy docs read back as ``None``.
    customer_since: Optional[str] = None
    # Feb 2026 · Stripe → CRM sync fields (populated by the BYO-Stripe
    # migration flow — see ``services/stripe_customer_sync.py``).
    # Redacted from public GET /customers responses (see the sanitizer
    # at routers/customers.py:532/855) — surfaces only via the admin
    # migration diff endpoint. Formalized here so the migration test
    # suite has a schema-validated shape to write against.
    stripe_customer_id: Optional[str] = None
    stripe_default_payment_method_id: Optional[str] = None
    stripe_card_brand: Optional[str] = None
    stripe_card_last4: Optional[str] = None
    stripe_synced_at: Optional[str] = None
    stripe_sync_status: Optional[str] = None  # attached | no_card | imported

    # ─── Feb-2026 · Multi-Contact Phase 1 · automations-mute ───
    # Distinct from ``is_muted`` (which suppresses auto-scheduling,
    # route-suggest, dashboard counts — kept UNCHANGED). This new
    # field exclusively gates comms fan-out via
    # ``services.customer_multi_contact.active_email_recipients`` /
    # ``active_phone_recipients`` when ``context="automation"``.
    # Manual admin sends (``context="manual"``) bypass this gate.
    # See /app/memory/FEATURE_MULTI_CONTACT_PHASE1.md for the
    # 1B "parallel field" decision rationale.
    automations_muted: Optional[bool] = False
    automations_muted_reason: Optional[str] = None
    automations_muted_at: Optional[str] = None      # ISO-8601 UTC
    automations_muted_by: Optional[str] = None      # user id
    # Forward-compat: ``"all"`` is the only value honored in Phase 1
    # (email + sms both muted). ``"email"`` / ``"sms"`` persist as-is
    # but are treated identically to ``"all"`` by the helpers until
    # per-channel wiring lands.
    automations_muted_channel: Optional[str] = "all"

    @field_validator("pool_gallons")
    @classmethod
    def _check_pool_gallons(cls, v):
        if v is None:
            return v
        # Reject booleans (bool is a subtype of int in Python).
        if isinstance(v, bool):
            raise ValueError("pool_gallons must be an integer")
        if not isinstance(v, int):
            raise ValueError("pool_gallons must be an integer")
        if v < 1 or v > 500000:
            raise ValueError("pool_gallons must be between 1 and 500000")
        return v


class CustomerBulkAction(BaseModel):
    ids: List[str]
    action: str                                   # "add_tag" | "remove_tag" | "add_waitlist" | "remove_waitlist" | "delete"
    tag: Optional[str] = None


class TechnicianIn(BaseModel):
    name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    specialty: Optional[str] = "Pool Service"
    avatar: Optional[str] = ""


class LanaTodo(BaseModel):
    """Phase 49 · Feb-2026 — admin-only per-user todos captured by Lana
    (voice or text). Stored in ``db.admin_todos``. Reminders live in
    ``db.admin_reminders`` (see :class:`LanaReminder`)."""
    id: str
    tenant_id: str
    user_id: str
    text: str
    due_at: Optional[str] = None
    completed: bool = False
    created_at: str
    updated_at: str


class LanaReminder(BaseModel):
    """Phase 49 · Feb-2026 — single-fire SMS reminder. Cron in
    :mod:`services.lana.reminder_cron` polls every minute; live SMS is
    gated on ``LANA_SMS_LIVE=1`` (default: dry-run)."""
    id: str
    tenant_id: str
    user_id: str
    text: str
    remind_at: str
    phone: Optional[str] = None
    sent: bool = False
    sent_at: Optional[str] = None
    sent_mode: Optional[str] = None
    created_at: str


class JobIn(BaseModel):
    title: str
    customer_id: str
    technician_id: Optional[str] = None
    address: Optional[str] = ""
    service_type: Optional[str] = "Pool Cleaning"
    scheduled_date: Optional[str] = None
    notes: Optional[str] = ""
    price: Optional[float] = 0.0
    status: Optional[str] = "pending"
    # Feb-2026 MP1 — Multi-property. Optional at the schema level so
    # legacy callers don't break; routers/jobs.create_job enforces the
    # "required when customer has ≥2 properties" rule and auto-assigns
    # when exactly 1 property exists.
    property_id: Optional[str] = None
    # Phase 55-a · Aug-2026 — Homeworks importer FK. Nullable; enables
    # per-batch rollback via ``delete_many({import_batch_id: X})``.
    import_batch_id: Optional[str] = None
    # Feb 2026 · Work-class dimension. Orthogonal to ``job_type``
    # (which is pool/landscape department discipline). Values:
    # ``"service"`` (routine visit) | ``"repair"`` (fix-something
    # visit). Default ``"service"`` — legacy jobs implicitly count
    # as service via the read-time helper. Enables per-tech counter
    # split on ``/api/schedule/today``, ``/api/technicians``, and
    # ``/api/team``. See ``services/work_class.py``.
    work_class: Optional[str] = "service"
    # Feb-2026 · Crew Phase A overlay — an optional crew binding
    # co-exists with ``technician_id`` (the crew is an overlay, not
    # a replacement — locked product decision). Validated in
    # ``routers/jobs.py::create_job`` against the caller's tenant.
    crew_id: Optional[str] = None


class JobUpdate(BaseModel):
    status: Optional[str] = None
    technician_id: Optional[str] = None
    notes: Optional[str] = None
    scheduled_date: Optional[str] = None
    # Feb-2026 · Checklist reclassification — added so a tech (or admin)
    # can retag a misclassified job from the Job Checklist "Chemical
    # Readings" empty-state picker. The backend `_detect_template()` in
    # routers/service_reports.py keys off `service_type`/`job_type`/
    # `title`, so mutating this field is what makes the readings input
    # matrix repopulate on the next GET. Tech-scope is already enforced
    # by the ownership guard at routers/jobs.py::update_job (403 when
    # `job.technician_id != user.technician_id`).
    service_type: Optional[str] = None
    # Feb-2026 · Crew-assignment Phase A — the schedule/dispatch admin
    # can now overlay a crew on a job so every crew member sees it on
    # their personal schedule. `crew_id` is validated in
    # routers/jobs.py::update_job against the caller's tenant and
    # enriched with `crew_name` + `crew_color`. RBAC is admin/manager
    # only for crew changes (enforced in the handler, not the model).
    # ``technician_id`` is not cleared — the tech stays as lead per
    # the locked product decision (overlay semantics).
    crew_id: Optional[str] = None
    # Feb 2026 · Work-class retag. Admin/manager (or tech via own-job
    # ownership) may retag service ↔ repair after create. Validation
    # in the handler (rejects anything but "service"/"repair").
    work_class: Optional[str] = None
    # Feb 2026 · Address picker on Job Edit — multi-property customers
    # can retag which of their properties a job services. Validated in
    # ``routers/jobs.py::update_job`` (must exist in tenant AND belong
    # to the job's customer). Handler re-snapshots address + coords
    # from the target property onto the job.
    property_id: Optional[str] = None
    # Free-text title/subject for the job card. Editable from the
    # Schedule inline edit modal.
    title: Optional[str] = None
    # Mobile Phase 2 · Feb-2026 — tech-wins conflict marker. When
    # set, the flush worker declares this write reflects a tech's
    # local edit taken while offline. The handler compares this to
    # the server's current ``updated_at`` and, if the server is
    # newer, logs the overwrite to ``mobile_write_conflicts`` for
    # audit — the tech's write is ACCEPTED regardless (per user
    # directive). Never persisted onto the job document.
    client_updated_at: Optional[str] = None
    # Phase C1 · Feb-2026 — admin-override follow-up controls for
    # the Sales Pipeline Follow-up column. ``follow_up_at`` is auto-
    # populated on the ``→ completed`` transition (recurring cadence
    # if a template resolves; else default 14d). An admin/manager
    # PATCH here overrides that value. ``needs_follow_up`` is a
    # boolean flag consumed by the Kanban Follow-up column when no
    # explicit ``follow_up_at`` is set. Techs are NOT allowed to set
    # either field (enforced in ``routers/jobs.py::update_job``).
    follow_up_at: Optional[str] = None
    needs_follow_up: Optional[bool] = None
    # Feb-2026 · Jobs Overhaul Phase 3 — editable Job Costing.
    # Admin can override the computed baseline/actual per bucket
    # from the JobDetail Costing panel. Shape:
    #   {"labor":     {"budgeted_cents": int, "actual_cents": int},
    #    "materials": {"budgeted_cents": int, "actual_cents": int},
    #    "equipment": {"budgeted_cents": int, "actual_cents": int}}
    # Each inner key is INDEPENDENTLY optional — missing keys fall
    # back to the computed value in ``GET /jobs/{jid}/costing``.
    # ``routers/budgets.py::job_costing`` merges these over the
    # computed baseline/actual before recomputing progress + net
    # profit + margin.
    #
    # Phase 3b write contract (locked):
    #   * Callers MUST send the FULL merged dict every PUT — the
    #     backend ``$set``s this field atomically and does NOT
    #     merge partial writes. A caller that sends only
    #     ``{"labor": {"budgeted_cents": X}}`` CLOBBERS any
    #     pre-existing ``materials`` / ``equipment`` / inner
    #     fields. The FE panel hydrates from
    #     ``GET /jobs/{jid}/costing`` (which echoes the raw
    #     ``costing_overrides`` dict as a top-level key) before
    #     mutating one cell, then re-sends the full dict.
    #   * Shape validation + admin-equivalent role gate live in
    #     ``routers/jobs.py::update_job`` (403 for non-admin
    #     when this key appears in the payload; 400 on malformed
    #     bucket keys, inner keys, or non-non-negative-int values).
    costing_overrides: Optional[Dict[str, Dict[str, Any]]] = None
    # Feb-2026 · Jobs Overhaul Phase 3 — editable Customer field on
    # JobDetail. Admin re-points the job to a different customer;
    # the denorm ``customer_name`` is re-resolved server-side (same
    # pattern as ``POST /jobs``) and the address re-snapshot runs
    # when a property_id is set or auto-resolves.
    customer_id: Optional[str] = None
    # Feb-2026 · Jobs Overhaul Phase 3 — Price / Service Category
    # parity with JobNew (Phase 1) + ScheduleJobEditModal (Phase 2).
    # All three surfaces (JobNew, Edit modal, JobDetail inline tile)
    # now round-trip through the same wire fields.
    price: Optional[float] = None
    service_category_id: Optional[str] = None
    service_category_name: Optional[str] = None
    # Feb-2026 · Jobs Overhaul Phase 3b — inline Start Time editor
    # on the Scheduled tile of ``/jobs/[id]``. Shape = ISO 8601
    # datetime string (same as ``scheduled_date`` which is plain
    # ``str`` without datetime parsing). The FE synthesizes the
    # ISO via ``new Date(`${scheduled_date}T${hhmm}:00`).toISOString()``
    # on commit — see ``frontend/src/pages/jobs/JobDetail.jsx``
    # Start Time ``InlineEditTile``. Downstream read paths
    # (analytics, dispatch, portal) already consume this field.
    scheduled_start: Optional[str] = None


class JobArriveIn(BaseModel):
    lat: float
    lng: float
    site_lat: Optional[float] = None
    site_lng: Optional[float] = None
    price: Optional[float] = None
    # Feb-2026 · P37a — optional accuracy metadata from the mobile
    # geofence event; used only for the audit log breadcrumb, never
    # gates the timer start.
    accuracy: Optional[float] = None
    # Feb-2026 · Job Arrival unify · mobile arrival ergonomics.
    # When ``source`` is present it drives ``timer_start_method`` on
    # the job doc. When absent, the legacy default
    # (``"gps_arrival"``) is stamped so existing callers keep the
    # exact same audit shape. Whitelist enforced in the router.
    source: Optional[str] = None


class FieldReportUpdate(BaseModel):
    checklist: Optional[List[dict]] = None
    chemical_readings: Optional[dict] = None
    chemicals_added: Optional[List[dict]] = None
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None


class LineItem(BaseModel):
    description: str
    quantity: float = 1
    unit_price: float = 0.0
    category: str = "Pool"
    # Feb-2026 · PDF Importer Sub-phase A — short-label distinct
    # from the free-text ``description``.  Populated by the vision
    # extractor in Sub-phase B; grandfathers to None for every row
    # written before this ships (including all legacy pricebook +
    # manually-typed lines).  Nullable + Optional so the router
    # accepts writes that omit the field entirely.
    item_name: Optional[str] = None
    # PDF-FIX-D · Feb-2026 — line_total verbatim from PDF import.
    # Preserves the printed per-line total from the source PDF
    # (may reflect discounts / rounding invisible to a naive
    # ``qty × unit_price`` recompute).  Nullable for legacy /
    # non-PDF lines that never populated it — read paths
    # (FE display + tax reports) fall back to ``qty × unit_price``
    # when None.  Pydantic v2 ``extra='ignore'`` on the parent
    # collection means the field silently drops from legacy line
    # writes; PDF import path passes it through the raw dict at
    # commit-time.
    line_total: Optional[float] = None
    # Feb-2026 · Income Category enforcement — optional per line.
    income_category_id: Optional[str] = None
    # Phase K71 · Feb-2026 — Estimate line-item edit + Service/Income
    # category parity. ``service_category_id`` mirrors the K71 dropdown
    # in the inline line-item editor; ``long_description`` is the new
    # multi-line secondary text shown under the bold item name (hidden
    # on customer-facing PDF + portal). BOTH fields are required for
    # NEW items typed after K71 ships; legacy grandfathered line items
    # (missing both K71 fields) remain valid. Cap 500 chars enforced
    # by the router.
    service_category_id: Optional[str] = None
    long_description: Optional[str] = None
    # Feb-2026 · PB1 · Price-book linkage — when the line was created
    # from a pricebook item, the id sticks so the profit report can
    # resolve the service_category + fall back to the current cost.
    item_id: Optional[str] = None
    # Phase 56-d · Aug-2026 — dedicated pricebook FK for the
    # supplier-spend report. Additive alongside the existing
    # ``item_id`` (which is used broadly). Nullable → legacy line
    # items grandfather to null and bucket into "Uncategorized" on
    # the report. Frontend line-item picker plumbs the value when
    # the user picks a pricebook item from the datalist.
    pricebook_item_id: Optional[str] = None
    # Feb-2026 · PB1 · Immutable margin snapshots. Written once at
    # create-time (and by the backfill script for historical rows).
    # Once set, the update path must never overwrite them — that
    # would silently rewrite historical margin data every time an
    # admin tweaks a description.
    retail_price_snapshot: Optional[float] = None
    wholesale_price_snapshot: Optional[float] = None
    labor_cost_snapshot: Optional[float] = None
    # Feb-2026 · Pricebook × Profit-Reporting Phase 2 — per-line
    # admin overrides that live ALONGSIDE the write-once snapshots.
    # ``None`` means "no override, use the snapshot". Effective values
    # at read: ``effective_wholesale = wholesale_cost_override ??
    # wholesale_price_snapshot``; same posture for labor. Categories
    # follow the same override-first pattern. Admin-only — stripped
    # from every customer-facing payload by the estimate/invoice
    # viewers (see routers/estimate_viewer.py::_CUSTOMER_LINE_HIDDEN).
    wholesale_cost_override: Optional[float] = None
    labor_cost_override: Optional[float] = None
    income_category_id_override: Optional[str] = None
    service_category_id_override: Optional[str] = None
    # Feb-2026 · Pricebook item_type — set by the estimate/invoice
    # writer path when the line references a service and the operator
    # overrides the unit_price. Products may NOT set this — the
    # writer rejects such lines with 400. Nullable so legacy lines
    # (no ``item_type`` on the referenced item) grandfather to false.
    overridden_price: Optional[bool] = False
    # Feb-2026 · Invoice inline edit + pricebook writeback — opt-in
    # per line. When ``True``, the invoice writer path fans out
    # AFTER a successful save and updates (or creates) the linked
    # pricebook item using this line's ``unit_price``, ``category``
    # and ``description``. Never mutates the pricebook if the invoice
    # save fails. Audited to ``db.pricebook_writeback_events``.
    pricebook_writeback: Optional[bool] = False


class QuoteIn(BaseModel):
    # Phase 2 · Feb-2026 · Quote-to-Lead Recipient.
    customer_id: Optional[str] = None
    recipient_type: Optional[str] = None  # 'customer' | 'lead'
    recipient_id: Optional[str] = None
    title: str
    doc_type: str = "quote"  # quote | invoice
    line_items: List[LineItem] = []
    tax_rate: float = 0.0
    due_date: Optional[str] = None  # YYYY-MM-DD (invoices)
    notes: Optional[str] = ""
    terms: Optional[str] = None  # None → auto-fill from /settings/terms defaults
    # Task H0 · Feb-2026 — Historical Invoice Date Backfill.
    # Optional admin-only override on the create path. When absent
    # the router server-stamps ``now()`` (existing behaviour).
    # When present + caller role ∈ {admin, super_admin, owner},
    # ``services.quotes.date_override.resolve_date_override``
    # coerces to UTC, validates future/ancient thresholds, and
    # emits a WARN audit log. Non-admin senders → field silently
    # dropped, no override audit fields written, no log. This is
    # the foundation the Task H PDF Invoice Importer plugs into.
    created_at: Optional[datetime] = None
    # Feb-2026 · PDF Importer Sub-phase A — historical document date
    # as embedded in the source paper/PDF invoice (distinct from the
    # ``created_at`` ingest timestamp).  Persisted as an ISO string
    # (``YYYY-MM-DD`` or full ISO 8601) so the wire format matches
    # the neighbouring ``due_date`` convention.  On the PDF-import
    # path (Sub-phase B/C) the mapper stamps BOTH ``doc_date`` and
    # ``created_at`` with the extracted historical date per rulings
    # R1/R2; existing PDF imports get ``doc_date`` back-filled from
    # ``created_at`` via ``services/migrations/pdf_doc_date_backfill_v1``.
    # Nullable + Optional so non-PDF writes (manual quote creation,
    # legacy DB rows) grandfather to ``None`` cleanly.  Reports are
    # extended to ``$or`` this field in a later sub-phase per R7.
    doc_date: Optional[str] = None
    # Feb-2026 MP1.5 — Multi-property billing plumbing. Optional pointer
    # to the ``properties`` row this doc bills against. When the customer
    # owns exactly one active property the router auto-assigns it. When
    # the customer owns multiple, callers should send an explicit id;
    # leaving it null is allowed (consolidated-across-properties case).
    property_id: Optional[str] = None
    # Phase 55-a · Aug-2026 — Homeworks importer FK. Nullable; covers
    # BOTH quotes and invoices (same collection family). Enables
    # per-batch rollback.
    import_batch_id: Optional[str] = None
    # Phase K79 · Feb-2026 — Grouped customer-facing estimate view.
    # NEW quotes default to grouped-display ON; existing quotes are
    # snapped to false by scripts/k79_customer_group_display_migration.py
    # so they keep the itemized view their author designed.
    customer_group_display: Optional[bool] = True
    customer_group_descriptions: Optional[Dict[str, str]] = None


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · PDF Importer Sub-phase A — first-class Payment model.
# ═══════════════════════════════════════════════════════════════════
class Payment(BaseModel):
    """Payment row persisted in ``db.payments``.

    Historically ``db.payments`` was populated only by
    ``services/stripe_billing_history_sync.py`` (dict-shaped inserts).
    Sub-phase A introduces this first-class Pydantic model so the
    PDF Importer's Sub-phase C commit path can validate + shape
    payment rows uniformly.  Field shape mirrors the stripe sync
    doc so both provenance families round-trip through a single
    read query.

    * ``amount_cents`` — integer cents; matches the stripe sync
      convention.  Never store amounts as float.
    * ``imported_from`` — provenance sentinel; ``"stripe_billing_history_sync"``
      for the stripe path, ``"pdf_import"`` for Sub-phase C.
    * ``doc_date`` — the PDF-embedded payment date; distinct from the
      audit-only ``imported_at`` (actual DB insert time) and from
      ``created_at`` which is stamped with the same historical date
      per rulings R1/R2 so revenue/profit reports bucket correctly.
    * ``matched`` — set to ``True`` only when both ``customer_id``
      AND ``invoice_id`` were resolved by the mapper; ``False``
      surfaces the row in the Sub-phase E review UI so an admin can
      manually pair it.
    """
    id: Optional[str] = None
    tenant_id: str
    customer_id: Optional[str] = None
    invoice_id: Optional[str] = None
    amount_cents: int
    currency: str = "USD"
    payment_method: Optional[str] = None  # check | cash | card | ach | other
    reference: Optional[str] = None  # check # / txn ref / confirmation code
    doc_date: Optional[str] = None
    created_at: Optional[str] = None
    imported_from: str = "pdf_import"
    imported_at: Optional[str] = None
    matched: bool = False


class QuoteUpdate(BaseModel):
    # Feb-2026 · Task 6 · Defect fix — write side accepts the same
    # field name the read side emits (``terms_and_conditions``) so
    # API consumers can round-trip GET → PUT without renaming. The
    # legacy ``terms`` key is still accepted for one release and
    # logged as a deprecation warning by the router.
    title: Optional[str] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    terms_and_conditions: Optional[str] = None
    tax_rate: Optional[float] = None
    due_date: Optional[str] = None
    line_items: Optional[List[LineItem]] = None
    property_id: Optional[str] = None
    # Phase K79 · Feb-2026 — Admin toggles the customer-facing grouped
    # view and edits the optional per-category descriptions on the
    # quote editor. Both fields are money-neutral (server totals do
    # not recompute when either changes).
    customer_group_display: Optional[bool] = None
    customer_group_descriptions: Optional[Dict[str, str]] = None
    # Feb-2026 · Editable Sent Docs · Phase 1 — the frontend
    # confirm-dialog for editing a ``sent`` / ``accepted`` / ``paid``
    # doc sets this to ``true``, which unlocks the corresponding
    # statuses via ``services.quotes.status_gate``. Money-neutral
    # (not persisted, ignored by every field-level path below).
    acknowledged_lock_bypass: Optional[bool] = None
    # Optional operator note surfaced on the ``document_versions``
    # audit row for this edit.
    edit_reason: Optional[str] = None
    # Feb-2026 · Interactive Flipbook Estimate Viewer — per-estimate
    # opt-in. When ``flipbook_enabled=true`` the customer-facing
    # magic-link surface renders the estimate as a page-flip book
    # (react-pageflip) instead of the classic scrollable view. The
    # optional ``flipbook_background_ids`` list holds media-library
    # image IDs that render as page backgrounds. Both fields are
    # money-neutral and persist on the doc row.
    flipbook_enabled: Optional[bool] = None
    flipbook_background_ids: Optional[List[str]] = None
    # DOC-DATE-EDITING · Feb-2026 — admin-editable document date.
    # Routed through ``services.quotes.date_override`` for validation
    # (max 50y back, max now+60s, naive-UTC coerced). Role-gated to
    # ``{admin, super_admin, manager, owner}`` server-side.  Stamps
    # ``created_at_override_by`` + ``created_at_override_at`` on the
    # persisted doc so H0's "override vs real-time" audit trail
    # survives the post-create edit path.  Silently dropped (not
    # written) when the actor is outside the allowlist.
    created_at: Optional[datetime] = None


class TermsSettingsIn(BaseModel):
    default_quote_terms: Optional[str] = None
    default_invoice_terms: Optional[str] = None


class RecordPaymentIn(BaseModel):
    amount: float
    # Task H0 · Feb-2026 — Historical Invoice Date Backfill.
    # Optional admin-only override on the record-payment path.
    # ``record_payment`` in ``routers/quotes.py`` only stamps
    # ``paid_at`` when the payment transitions the invoice to
    # ``fully_paid=True`` — sending ``paid_at`` on a partial
    # payment silently defers the override (INFO log line with
    # ``deferred_reason=partial_payment``) rather than 400ing,
    # matching the least-surprise semantics locked in the halt
    # report. Resolution + validation delegated to
    # ``services.quotes.date_override.resolve_date_override``.
    paid_at: Optional[datetime] = None


class CategoryIn(BaseModel):
    name: str


class SetupSessionReq(BaseModel):
    return_url: str
    customer_id: Optional[str] = None


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = ""
    address: Optional[str] = ""

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password_strength(v)


class CreateLoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password_strength(v)


class CustomerProfileUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    billing_address: Optional[str] = None
    gate_code: Optional[str] = None
    avatar: Optional[str] = None


class PhotoIn(BaseModel):
    data: str  # base64 data URI
    label: Optional[str] = "photo"
    # Phase O4 · Feb-2026 — Client-UUID acceptance. The mobile app
    # mints a UUID for a photo offline; when the offline queue drains
    # we look up ``jobs.photos.id == client_uuid`` first and return
    # the existing job doc if the row is already there.  When absent
    # we persist ``photo.id = client_uuid`` so mobile can cross-reference
    # by its own id without a server round-trip.
    client_uuid: Optional[str] = None


class ServiceIssueIn(BaseModel):
    description: str
    cost: Optional[float] = None
    photo: Optional[str] = None  # base64 data URI
    # Phase O4 · Feb-2026 — Client-UUID acceptance (same semantics as
    # ``PhotoIn.client_uuid`` above).
    client_uuid: Optional[str] = None


class ServiceRequestIn(BaseModel):
    service_type: str = "Pool Cleaning"
    title: Optional[str] = ""
    scheduled_date: Optional[str] = None
    notes: Optional[str] = ""


class LeadIn(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    source: Optional[str] = "admin_manual"
    status: Optional[str] = "New"
    notes: Optional[str] = ""
    est_value: Optional[float] = 0.0
    address: Optional[str] = ""
    service_address: Optional[str] = None
    service_interest: Optional[str] = None  # Pool | Landscape | Both
    lat: Optional[float] = None
    lng: Optional[float] = None
    # Feb-2026 · P0 · Lead form address autofill (Google Places).
    # Autocomplete-supplied coordinates skip the on-save geocode
    # background call. Persisted alongside the legacy ``lat``/``lng``
    # keys so downstream consumers can read either name.
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class LeadUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    service_interest: Optional[str] = None
    service_address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    # Feb-2026 · P0 — lat/lng from autocomplete on edit.
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# Phase 8 · Feb 2026 — request models for the leads overhaul.
class LeadNoteIn(BaseModel):
    text: str


class LeadCloseLostIn(BaseModel):
    loss_reason: str


class PublicLeadIn(BaseModel):
    name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    service_address: Optional[str] = ""
    service_interest: Optional[str] = None
    notes: Optional[str] = ""
    turnstile_token: Optional[str] = None
    # Phase 10 · Feb 2026 — optional referral capture. Invalid codes
    # are silently ignored (do NOT 400 — spammy invalid codes must
    # never block a real inquiry).
    referral_code: Optional[str] = None
    # Feb-2026 · P0 · Lead form address autofill (Google Places) —
    # when both are supplied by the embedded widget's autocomplete
    # the server skips its on-save geocode call.
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ItemIn(BaseModel):
    name: str
    category: Optional[str] = "Service"
    unit: Optional[str] = "each"
    unit_price: float = 0.0
    taxable: Optional[bool] = True
    # Feb-2026 · Pricebook item taxonomy — "product" vs "service".
    # Products keep the existing locked-price behaviour and can carry
    # supplier prices / cost fields. Services have NO supplier data
    # and their unit price is EDITABLE per-customer on estimate /
    # invoice line items (see routers/quotes.py). Defaults to
    # ``product`` so every row that pre-dates this feature keeps its
    # current behaviour.
    item_type: Optional[str] = "product"
    # Feb-2026 · Service categories — higher-level business-unit
    # taxonomy attached to pricebook items. Required on new writes;
    # existing rows without one are grandfathered on reads.
    service_category_id: Optional[str] = None
    # Feb-2026 · PB1 · Internal cost fields (admin-only surface).
    wholesale_price: Optional[float] = 0.0
    labor_cost_default: Optional[float] = 0.0
    # Legacy ``tax_rate``/``description``/``active``/``sku`` are accepted
    # for backward compatibility with the existing Pricebook UI which
    # sends them via POST /items. Phase 56-e · Aug-2026 — legacy
    # ``cost`` removed from the write contract; existing rows in
    # Mongo may still have the field but new writes never set it.
    tax_rate: Optional[float] = 0.0
    description: Optional[str] = None
    active: Optional[bool] = True
    sku: Optional[str] = None
    # Phase 54a · Feb-2026 — wholesale-supplier import fields
    # (additive, all optional). ``supplier_id`` links the item to a
    # row in the ``suppliers`` collection (``null`` = manually entered,
    # not imported). ``external_sku`` is the supplier-side SKU used
    # for dedupe on the next sync. ``last_synced_at`` records the
    # most-recent successful sync touch. See ``routers/suppliers.py``
    # and ``services/suppliers/``.
    supplier_id: Optional[str] = None
    external_sku: Optional[str] = None
    last_synced_at: Optional[str] = None
    # Phase 56-b · Aug-2026 — Multi-supplier pricing.
    #   ``income_category_id`` — soft-link to db.income_categories.
    #                            Drives which suppliers appear on the
    #                            "Add item" modal supplier grid.
    #                            Nullable → legacy items grandfather
    #                            to "Uncategorized" in list views.
    #   ``supplier_prices``    — per-supplier cost, subdoc list of
    #                            ``{"supplier_slug": str, "cost_cents": int}``.
    #                            Empty list = no supplier prices.
    #                            Validated against pricebook_suppliers
    #                            in ``routers/items.py`` on writes.
    income_category_id: Optional[str] = None
    supplier_prices: List[Dict[str, Any]] = Field(default_factory=list)
    # Backlog #iii · Feb-2026 — Rich multi-supplier subdoc. New
    # authoritative source of truth for item-level supplier pricing.
    # Legacy ``supplier_prices`` + scalar ``wholesale_price`` are
    # kept as read-only mirrors regenerated on every write via
    # ``services.pricebook.cost.rebuild_mirrors``. Free-form supplier
    # name (no hard FK to ``suppliers`` / ``pricebook_suppliers``);
    # the autocomplete at ``GET /pricebook/supplier-names`` is UI
    # polish, not schema coupling.
    #
    # Row shape:
    #   {
    #     "id":            str (uuid),
    #     "supplier_name": str (required, plain text — free-form),
    #     "supplier_sku":  str (optional),
    #     "unit_cost":     float (>= 0 when set; None means unknown),
    #     "unit_size":     str (e.g. "25 lb", "gallon"),
    #     "last_updated":  str (ISO-8601),
    #     "notes":         str (optional, free-form),
    #   }
    suppliers: List[Dict[str, Any]] = Field(default_factory=list)


class BillingPlanIn(BaseModel):
    customer_id: str
    service: Optional[str] = "Monthly Pool Service"
    frequency: Optional[str] = "monthly"  # weekly | monthly | quarterly
    amount: float = 0.0
    next_run: Optional[str] = None
    active: Optional[bool] = True
    # Phase 56.17 — monthly anchor picker. Existing plans without the
    # field default to "first_of_month" at read time to preserve prior
    # behavior (no bulk migration required).
    run_schedule: Optional[str] = "first_of_month"

    @field_validator("run_schedule")
    @classmethod
    def _check_schedule(cls, v):
        v = (v or "first_of_month").strip().lower()
        if v not in ("first_friday", "second_friday", "third_friday", "fourth_friday", "first_of_month"):
            raise ValueError(
                "run_schedule must be one of: first_friday | second_friday | third_friday | fourth_friday | first_of_month"
            )
        return v


class BillingPlanUpdate(BaseModel):
    service: Optional[str] = None
    frequency: Optional[str] = None
    amount: Optional[float] = None
    next_run: Optional[str] = None
    active: Optional[bool] = None
    run_schedule: Optional[str] = None

    @field_validator("run_schedule")
    @classmethod
    def _check_schedule(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if v not in ("first_friday", "second_friday", "third_friday", "fourth_friday", "first_of_month"):
            raise ValueError(
                "run_schedule must be one of: first_friday | second_friday | third_friday | fourth_friday | first_of_month"
            )
        return v


class TenantSettingsUpdate(BaseModel):
    # Phase 56.17 — admin-editable tenant timezone. IANA name.
    # Defaults to America/Phoenix (Vistancia, AZ — no-DST) elsewhere in
    # the codebase; this update endpoint is the only way to change it.
    timezone: Optional[str] = None
    # Phase R1 · Feb-2026 — net-terms in days for AR aging + unpaid
    # invoices reporting. Nullable; defaults to 30 when unset (locked
    # in ``services/reporting/paid_date.build_effective_due_date_expr``
    # and ``ar_aging._resolve_net_terms``).
    net_terms_days: Optional[int] = None


class RepairIn(BaseModel):
    customer_id: str
    equipment: Optional[str] = "Pump"
    issue: str
    technician_id: Optional[str] = None
    cost: Optional[float] = 0.0
    status: Optional[str] = "open"  # open | diagnosing | awaiting_parts | repaired
    photos: Optional[List[str]] = []  # base64 data URIs


class RepairUpdate(BaseModel):
    status: Optional[str] = None
    technician_id: Optional[str] = None
    cost: Optional[float] = None
    issue: Optional[str] = None


class FormIn(BaseModel):
    name: str
    description: Optional[str] = ""
    slug: Optional[str] = None
    status: Optional[str] = "draft"  # draft | published
    fields: List[Any] = Field(default_factory=list)  # [{id,name,label,type,required,options,...}]
    destination: Optional[str] = "lead"  # lead | customer | quote_request
    notify_emails: Optional[List[str]] = None
    redirect_url: Optional[str] = None
    model_config = {"extra": "allow"}


class FormSubmitIn(BaseModel):
    values: dict = {}


class AutomationIn(BaseModel):
    name: str
    trigger: str  # e.g. lead_created, job_completed, invoice_unpaid
    action: str   # e.g. send_welcome_sms, request_review, send_reminder
    active: Optional[bool] = True


class AutomationUpdate(BaseModel):
    active: Optional[bool] = None
    name: Optional[str] = None
    trigger: Optional[str] = None
    action: Optional[str] = None


class CampaignIn(BaseModel):
    channel: Optional[str] = "email"  # email | sms
    subject: str
    body: Optional[str] = ""
    audience: Optional[str] = "all_customers"


class ReviewIn(BaseModel):
    customer_name: str
    rating: int = 5
    text: Optional[str] = ""
    source: Optional[str] = "Google"


class ReviewRespond(BaseModel):
    response: str


class CheckinIn(BaseModel):
    """Feb-2026 · Technician Check-In flow.

    Tightened payload for ``POST /api/checkins``. Required fields:

    * ``job_id`` — the workorder/job this check-in is bound to.
    * ``latitude`` / ``longitude`` — the tech's GPS capture. Accepts
      the legacy short aliases ``lat`` / ``lng`` for backwards
      compatibility with the marketing-map admin path.
    * ``note`` — 1..2000 chars of free text. This is the customer-
      facing description that will be rewritten by the LLM and
      surfaced on the public map.
    * ``photo_file_ids`` — 1..5 file ids previously uploaded via
      ``POST /api/files/upload`` with ``purpose='public_checkin'``
      and ``linked_entity_type='public_checkin'``.

    ``address`` is kept optional for backwards compatibility with
    the marketing map pin admin page — the customer's address is
    the source of truth for the public pin, this field only exists
    for human-readable dashboard display.
    """
    job_id: str = Field(..., min_length=1)
    latitude: float = Field(
        ..., ge=-90, le=90,
        validation_alias=AliasChoices("latitude", "lat"),
    )
    longitude: float = Field(
        ..., ge=-180, le=180,
        validation_alias=AliasChoices("longitude", "lng"),
    )
    note: str = Field(..., min_length=1, max_length=2000)
    photo_file_ids: List[str] = Field(..., min_length=1, max_length=5)
    address: Optional[str] = ""

    model_config = {"populate_by_name": True}


class AIChatIn(BaseModel):
    employee_id: str
    message: str
    session_id: Optional[str] = None


class AccessUpdate(BaseModel):
    role: str
    module: str
    enabled: bool


class CheckoutRequest(BaseModel):
    success_url: str
    cancel_url: str


class MessageIn(BaseModel):
    text: str


class BookIn(BaseModel):
    date: str
    label: str


class SeoKeywordReq(BaseModel):
    seed: str
    location: Optional[str] = "Vistancia, Arizona"


class SeoArticleReq(BaseModel):
    keyword: str
    title: Optional[str] = None
    tone: Optional[str] = "friendly, professional"
    word_count: Optional[int] = 800


class SeoAuditReq(BaseModel):
    keyword: str
    content: Optional[str] = None
    article_id: Optional[str] = None


class WpSettingsIn(BaseModel):
    url: str
    username: str
    app_password: str


class SeoPublishReq(BaseModel):
    status: Optional[str] = "publish"  # draft | publish


class SeoScheduleReq(BaseModel):
    mode: Optional[str] = "auto"  # auto (weekly drip) | manual (explicit date)
    scheduled_for: Optional[str] = None  # ISO datetime, required for manual mode


class SeoScheduleSettings(BaseModel):
    enabled: Optional[bool] = True
    paused: Optional[bool] = False
    day_of_week: Optional[int] = 0  # 0=Mon ... 6=Sun
    hour: Optional[int] = 9
    minute: Optional[int] = 0
    publish_as: Optional[str] = "draft"  # draft | publish


class GbpSettingsIn(BaseModel):
    client_id: str
    client_secret: str
    redirect_uri: str


class GbpPostIn(BaseModel):
    location: str  # full resource name: accounts/x/locations/y
    summary: str
    cta_url: Optional[str] = None
    action_type: Optional[str] = "LEARN_MORE"  # LEARN_MORE | BOOK | ORDER | CALL | SIGN_UP


class GbpReplyIn(BaseModel):
    review_name: str  # full resource name of the review
    comment: str


class GbpAiPostReq(BaseModel):
    article_id: str


class GbpAiReplyReq(BaseModel):
    review_text: Optional[str] = ""
    rating: Optional[int] = 5
    reviewer_name: Optional[str] = ""


class GbpBusinessUpdate(BaseModel):
    location: str
    phone: Optional[str] = None
    website: Optional[str] = None
    regular_hours: Optional[dict] = None  # passthrough {periods:[...]} per GBP schema


class GbpAutopost(BaseModel):
    enabled: bool


class GbpCalendarEdit(BaseModel):
    summary: Optional[str] = None
    cta_url: Optional[str] = None


class CardCompanyIn(BaseModel):
    name: Optional[str] = None
    region: Optional[str] = None
    tagline: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    google_review: Optional[str] = None
    logo: Optional[str] = None  # base64 data URI


class CardPersonalIn(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class ConvertJobIn(BaseModel):
    service_type: Optional[str] = "Pool Service"
    scheduled_date: Optional[str] = None
    price: Optional[float] = None
    technician_id: Optional[str] = None


class ConvertQuoteIn(BaseModel):
    title: Optional[str] = None
    unit_price: Optional[float] = None
    tax_rate: Optional[float] = 0.0


class DocumentIn(BaseModel):
    customer_id: str
    name: str
    type: Optional[str] = "document"
    data: str  # base64 data URI or external URL


class MaintScheduleIn(BaseModel):
    customer_id: str
    type: str  # filter | salt_cell
    scheduled_date: str  # YYYY-MM-DD
    technician_id: Optional[str] = None
    interval_days: Optional[int] = None  # optionally update the pool's cadence


class MaintSettingsIn(BaseModel):
    filter_interval_days: Optional[int] = None
    salt_cell_interval_days: Optional[int] = None


class MaintBulkIn(BaseModel):
    scheduled_date: str  # YYYY-MM-DD
    technician_id: Optional[str] = None


class PunchIn(BaseModel):
    lat: float
    lng: float


class CoverageIn(BaseModel):
    source_technician_id: str
    target_technician_id: str
    scope: str = "day"  # day | week
    date: Optional[str] = None  # YYYY-MM-DD; required for scope=day, anchor for scope=week


class EstimateLineIn(BaseModel):
    category: str = "Material"  # Material | Labor | Subcontractor | Equipment | Other
    description: str = ""
    quantity: float = 1
    unit_cost: float = 0.0
    item_id: Optional[str] = None


class EstimateIn(BaseModel):
    customer_id: str
    title: str
    line_items: List[EstimateLineIn] = []
    overhead_pct: float = 0.0
    margin_pct: float = 0.0
    notes: Optional[str] = ""
    terms: Optional[str] = None  # None → auto-fill from /settings/terms defaults
    # Feb-2026 MP1.5 — Multi-property estimate plumbing. Same semantics
    # as ``QuoteIn.property_id``: optional pointer to the property the
    # estimate is scoped to. Carried through on conversion to a quote.
    property_id: Optional[str] = None


class EstimateSettingsIn(BaseModel):
    overhead_pct: Optional[float] = None
    margin_pct: Optional[float] = None


class EstimateTemplateIn(BaseModel):
    name: str
    line_items: List[EstimateLineIn] = []
    overhead_pct: float = 0.0
    margin_pct: float = 0.0


class D2DKnockIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = ""
    name: Optional[str] = ""
    phone: Optional[str] = ""
    disposition: str = "not_home"  # not_home | not_interested | callback | interested | sold
    notes: Optional[str] = ""
    zpid: Optional[str] = None  # Zillow property id when logged from a sold-lead pin
    sold_price: Optional[float] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _outcome_alias(cls, data):
        # Accept `outcome` as an alias for `disposition` (mobile clients).
        if isinstance(data, dict) and "outcome" in data and not data.get("disposition"):
            data = {**data, "disposition": data["outcome"]}
        return data


class D2DKnockUpdate(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    disposition: Optional[str] = None
    notes: Optional[str] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _outcome_alias(cls, data):
        if isinstance(data, dict) and "outcome" in data and not data.get("disposition"):
            data = {**data, "disposition": data["outcome"]}
        return data


class MaintLogIn(BaseModel):
    psi: Optional[float] = None
    filter_condition: Optional[str] = None
    salt_ppm: Optional[float] = None
    cell_condition: Optional[str] = None
    notes: Optional[str] = None
    photos: Optional[List[dict]] = None  # [{label, data(base64)}]


# ─── Phase 56.13a — Training subsystem models ──────────────────────────────
# Multi-tenant training modules for internal upskilling. System modules
# (is_system=True, no tenant_id) are seeded via backend.seed.training_cpo
# and are visible to every tenant read-only. Custom modules
# (is_system=False, tenant_id set) are per-tenant and admin-editable.
#
# IP-safety: training content shipped in system modules is 100% original,
# authored in-house. External standards (ANSI/APSP-11, CDC MAHC, VGB Act,
# etc.) are cited by name and external link only — never republished.

class TrainingLesson(BaseModel):
    id: str
    title: str
    body_md: str
    order: int = 0
    word_count: Optional[int] = 0


class TrainingQuizChoice(BaseModel):
    id: str
    text: str


class TrainingQuizQuestion(BaseModel):
    id: str
    prompt: str
    choices: List[TrainingQuizChoice]
    correct_choice_ids: List[str]  # invariant: len == 1 (seed test enforces)
    explanation: Optional[str] = ""
    chapter_ref: Optional[str] = None


class TrainingQuiz(BaseModel):
    passing_score: float = 0.75
    questions: List[TrainingQuizQuestion] = []


class TrainingModuleIn(BaseModel):
    """Payload for admin-created custom modules. System modules cannot be
    created / edited / deleted through the API — only via the seed script."""
    code: str
    title: str
    department: Optional[str] = "pool"     # pool | landscaping | both
    description: Optional[str] = ""
    lessons: Optional[List[TrainingLesson]] = []
    quiz: Optional[TrainingQuiz] = None
    badge_label: Optional[str] = ""
    disclaimer: Optional[str] = ""

    @field_validator("department")
    @classmethod
    def _check_dept(cls, v):
        v = (v or "pool").strip().lower()
        if v not in ("pool", "landscaping", "both"):
            raise ValueError("department must be one of: pool, landscaping, both")
        return v

    @field_validator("code")
    @classmethod
    def _check_code(cls, v):
        v = (v or "").strip().lower()
        if not re.match(r"^[a-z0-9][a-z0-9_\-]{1,60}$", v):
            raise ValueError("code must be lowercase, 2-61 chars, [a-z0-9_-]")
        return v


class TrainingModuleUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    description: Optional[str] = None
    lessons: Optional[List[TrainingLesson]] = None
    quiz: Optional[TrainingQuiz] = None
    badge_label: Optional[str] = None
    disclaimer: Optional[str] = None


class TrainingProgressIn(BaseModel):
    lesson_id: str


class TrainingQuizSubmit(BaseModel):
    # question_id -> chosen choice_id
    answers: dict


# ─── Phase 56.13a-commit — Certificate models ──────────────────────────────
# One certificate per (tenant_id, user_id, module_code). Auto-awarded on
# first passing quiz attempt (score >= passing_score). On subsequent passes
# with a higher score, the existing cert's `quiz_score` is upgraded and the
# PDF is regenerated on-demand (no duplicate rows).
#
# Certificate ID format: {MODULE_UPPER}-{YEAR}-{SEQ:06d} where SEQ is a
# monotonic per-tenant counter. Example: CPO-PREP-2026-000042.

class TrainingCertificate(BaseModel):
    id: str                          # UUID
    certificate_id: str              # human-readable, e.g. CPO-PREP-2026-000042
    tenant_id: str
    user_id: str
    module_code: str
    module_title: str
    user_name_snapshot: str
    tenant_name_snapshot: str
    quiz_score: float                # 0.0 – 1.0 (persist as fraction; render as %)
    awarded_at: str
    updated_at: Optional[str] = None



# ═══════════════════════════════════════════════════════════════════
# Phase 52.1a · Feb-2026 — Walkie live-streaming models.
#
# The existing Phase 51a walkie_channels + walkie_messages collections
# are stored as raw dicts (no dedicated Pydantic classes). Phase 52.1a
# introduces the ``walkie_live_sessions`` collection for tracking
# active WebRTC signaling rooms and adds two flags to ``walkie_channels``.
# The models below are the canonical serialised shape callers should
# validate against; collection writes still go through the router
# helpers so we don't disrupt Phase 51a's write path.
#
# `supports_live` defaults to True — existing channels lack the field
# on Mongo but the from_mongo readers below coerce a missing field to
# True so every legacy row is "live-capable" by default.
# `live_only` defaults to False.
# ═══════════════════════════════════════════════════════════════════
class WalkieChannel(BaseModel):
    id: str
    tenant_id: str
    kind: str                          # "all_hands" | "department" | "direct" | "live_room"
    department: Optional[str] = None
    member_user_ids: List[str] = Field(default_factory=list)
    name: Optional[str] = None
    pinned_message_id: Optional[str] = None
    supports_live: bool = True         # NEW — every channel is live-capable unless flipped off
    live_only: bool = False            # NEW — dedicated live-only channel (no async posts)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any]) -> "WalkieChannel":
        """Coerce a raw Mongo row into a WalkieChannel — supplies
        defaults for the two new fields when reading legacy rows that
        predate Phase 52.1a."""
        payload = dict(doc)
        payload.pop("_id", None)
        payload.setdefault("supports_live", True)
        payload.setdefault("live_only", False)
        payload.setdefault("member_user_ids", [])
        # created_at / updated_at may be datetime — normalise to ISO
        for k in ("created_at", "updated_at"):
            v = payload.get(k)
            if v is not None and not isinstance(v, str):
                try:
                    payload[k] = v.isoformat()
                except Exception:
                    payload[k] = None
        return cls(**payload)


class WalkieLiveSession(BaseModel):
    """A single live WebRTC signaling session for one channel.

    Sessions are open when created (first ``join``) and closed when
    the last peer leaves. The cleanup cron closes rows that outlive
    their in-process room (e.g. after a server restart).
    """

    id: str
    channel_id: str
    tenant_id: str
    started_at: str
    ended_at: Optional[str] = None
    started_by_user_id: str
    participant_user_ids: List[str] = Field(default_factory=list)
    recording_message_id: Optional[str] = None  # filled by Phase 52.1b/c auto-record

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any]) -> "WalkieLiveSession":
        payload = dict(doc)
        payload.pop("_id", None)
        payload.setdefault("participant_user_ids", [])
        return cls(**payload)


# ─── Phase 56-a · Aug-2026 — Pricebook Suppliers ────────────────────────
class PricebookSupplierIn(BaseModel):
    """Body for POST /api/pricebook/suppliers.

    Both ``slug`` and ``income_category_id`` are write-once — enforced
    at the router layer (PATCH ignores these fields even if sent).
    """
    slug: str
    display_name: str
    income_category_id: str


class PricebookSupplierPatch(BaseModel):
    """Body for PATCH /api/pricebook/suppliers/{id}.

    Only ``display_name`` and ``is_active`` are patchable. ``slug`` +
    ``income_category_id`` are write-once and rejected here silently
    (router does not read them off the model).
    """
    display_name: Optional[str] = None
    is_active: Optional[bool] = None


class PricebookSupplier(BaseModel):
    """Persistence shape for ``db.pricebook_suppliers``.

    Soft-delete columns mirror Fix #5 (Autobilling Runs) verbatim:
    ``deleted_at``, ``deleted_by_user_id``, ``restored_at``,
    ``restored_by_user_id``. ``is_seed=True`` marks the 13 built-in
    rows that ``seed_pricebook_suppliers`` inserts on first-boot.
    """
    id: str
    tenant_id: str
    slug: str
    display_name: str
    income_category_id: str
    is_active: bool = True
    is_seed: bool = False
    deleted_at: Optional[str] = None
    deleted_by_user_id: Optional[str] = None
    restored_at: Optional[str] = None
    restored_by_user_id: Optional[str] = None
    created_at: Optional[str] = None
    created_by_user_id: Optional[str] = None
    updated_at: Optional[str] = None




# ══════════════════════════════════════════════════════════════════
# Feb-2026 · MARCO · Sub-phase D — admin_todo Pydantic models.
#
# Persists to the ``marco_admin_todos`` collection (NOT Lana's
# Phase 49 ``admin_todos`` — those live under a distinct bucket
# per the Sub-phase D ruling #1 fork).  Rows are UI-driven from
# ``POST /api/admin/todos`` and tool-driven from
# ``create_admin_todo`` in the AI Employees tool loop.
# Sub-phase E's proactive cron will consume ``due_at`` +
# ``marco_pinged_at`` to dispatch reminder pings.
# ══════════════════════════════════════════════════════════════════
MARCO_ADMIN_TODOS_COLLECTION = "marco_admin_todos"

TodoPriority = Literal["low", "med", "high", "urgent"]
TodoStatus = Literal["open", "done", "snoozed", "deleted"]
TodoCreatedVia = Literal["marco_voice", "marco_chat", "admin_manual"]


class AdminTodoIn(BaseModel):
    """Request body for POST /api/admin/todos (manual admin create)."""
    title: str = Field(..., min_length=1, max_length=280)
    due_at: str = Field(..., min_length=1)   # ISO datetime (tz-aware)
    priority: TodoPriority = "med"
    notes: Optional[str] = Field(None, max_length=2000)


class AdminTodoPatch(BaseModel):
    """Partial-update body for PATCH /api/admin/todos/{id}.

    All fields optional — router applies only non-None fields.
    Status transitions to ``done`` auto-stamp ``completed_at``.
    """
    title: Optional[str] = Field(None, min_length=1, max_length=280)
    due_at: Optional[str] = None
    priority: Optional[TodoPriority] = None
    notes: Optional[str] = Field(None, max_length=2000)
    status: Optional[TodoStatus] = None


class AdminTodoOut(BaseModel):
    """Response shape returned from GET / POST / PATCH."""
    id: str
    tenant_id: str
    title: str
    due_at: str
    priority: TodoPriority
    notes: Optional[str] = None
    status: TodoStatus = "open"
    created_by: str
    created_via: TodoCreatedVia = "admin_manual"
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    # Reserved for Sub-phase E — proactive cron stamps this after a
    # notification-bell + SSE dispatch to prevent double-fires.
    marco_pinged_at: Optional[str] = None
