# TD-98-be-sources Phase 1 Audit · Super-timeline misses `notification_dispatch_log` + `audit_events` + `delivery_error`

**Date:** Oct-2026 (post-TD-98-be-cleanup-retire ship + td-lessons-doc-4).
**Status:** Audit-only. No code edits in this phase.
**Pre-audit HEAD:** `d9f4912b2` (`td-lessons-doc-4`).
**Rogue-cron chain:** 18 (unchanged this window).
**Default-stance applied** (from `td-lessons-doc-4`): assume shipped until recon disproves. Confirmed Step 1 memory grep + Step 2 file-inventory recon on both web + mobile per codified protocol.

---

## 0 · Executive summary

**Scope-reality is clean**. Three sources that the retired `/customers/{cid}/communication-timeline` endpoint used to surface have NO reader on the Phase-B super-timeline (`/customers/{cid}/timeline` + `/customers/me/timeline`):

1. **`notification_dispatch_log`** — transactional sends (service-report emails, on-my-way SMS, F7 idempotent notifier output). ~362 rows in preview per prior TD-98-be-cleanup-mobile recon.
2. **`audit_events`** with `event_type ∈ _AUDIT_EVENT_TYPES` — specifically `portal_invite_bulk` (bulk portal invite dispatch), `job_edited_after_completion` (K6 late-edit audit), `invoice_auto_charged` (K14 bulk Stripe charge audit).
3. **`delivery_error`** field — only emitted by `_dispatch_to_item` + `_audit_to_item` on the retired endpoint; never surfaced on Phase-B items.

**Upstream groundwork intact.** `_dispatch_to_item` (`routers/communication_timeline.py:107-138`) + `_audit_to_item` (`:141-242`) + `_strip_admin_fields` (`:245-255`) are all preserved per the TD-98-be-cleanup-retire ship (`2f22725e1`) and ready to lift (or rewrite in the Phase-B shape — see §4 operator decision).

**Recommended disposition:** `BE-only ship` + optional thin FE validation (no new FE surface needed if the shape-adapter approach is chosen). Operator picks between **(a) wrap** (keep legacy helpers verbatim + add thin wrapping adapter) and **(b) rewrite** (new Phase-B-shape source helpers mirroring the pattern of `_lead_communications_to_items` / `_lead_inbound_sms_to_items`). See §4 for the full matrix.

**Headline finding:** this is **genuinely new source-restoration work**, not a reconciliation. No existing audit doc covers the Phase-B migration scope. No existing BE code reads `notification_dispatch_log` into the Phase-B pipeline. Scope-reality clean = the exception not the default per `td-lessons-doc-4` codification.

---

## 1 · Current state verified against repo

### 1.a · Preserved helpers (ready for migration)

| Helper | File:Line | Purpose | Portal-safe? |
|---|---|---|---|
| `_dispatch_to_item` | `communication_timeline.py:107-138` | Normalize `notification_dispatch_log` row → legacy item | ⚠️ Emits `actor_user_id` + `delivery_error` top-level |
| `_audit_to_item` | `communication_timeline.py:141-242` | Normalize `audit_events` row → legacy item (3 event-type branches) | ⚠️ Same |
| `_strip_admin_fields` | `communication_timeline.py:245-255` | Portal role: pop `actor_user_id` + `delivery_error` | ✅ Load-bearing privacy helper |
| `_load_customer` | `communication_timeline.py:70-78` | Admin + portal shared customer loader | ✅ Tenant-scoped |
| `_customer_addresses` | `communication_timeline.py:81-104` | `(emails, phones)` for `resolved_address` match | ✅ Pure |
| `_preview` | `communication_timeline.py:63-67` | Body-preview truncator (500 char cap) | ✅ Pure |

**Minor doc drift:** the retired-handler docstring at `:291` references `_load_dispatch` which was deleted during TD-98-be-cleanup-retire. Non-blocking — fix in the TD-98-be-sources ship doc commit.

### 1.b · Legacy query shapes (from `2f22725e1^` pre-retirement)

**`notification_dispatch_log`**:
```python
{
  "tenant_id": tenant["id"],
  "$or": [
    {"recipient_id": customer_id},
    {"resolved_address": {"$in": emails + phones}},  # if any
  ],
  "channel": {"$in": wanted_types},  # optional
}
```
Sort: `(sent_at DESC, reserved_at DESC)`. Limit: `_MAX_PER_COLLECTION = 200`.

**`audit_events`**:
```python
{
  "tenant_id": tenant["id"],
  "event_type": {"$in": _AUDIT_EVENT_TYPES},
  # _AUDIT_EVENT_TYPES = (portal_invite_bulk,
  #                        job_edited_after_completion,
  #                        invoice_auto_charged)
  "$or": [
    {"payload.customer_ids": customer_id},  # bulk payload
    {"payload.customer_id":  customer_id},  # single-row payload
  ],
}
```
Sort: `timestamp DESC`. Limit: 200.

Both queries are **tenant-scoped**. No cross-tenant leak surface in the legacy readers.

### 1.c · Current Phase-B item shape (modern)

Phase-B source helpers (`_marketing_deliveries_to_items`, `_quotes_to_items`, `_lead_communications_to_items`, `_lead_inbound_sms_to_items`, `_call_logs_to_items`, `_job_notes_to_items`, `_customer_notes_to_items`) emit:

```python
{
  "kind":            str,  # email / sms / invoice / estimate / call / note
  "subject":         str,
  "template_name":   str,
  "delivery_status": str,
  "created_at":      str,  # ISO
  "ref_type":        str,  # collection source hint
  "ref_id":          str,
  "recipient":       str,
  "trigger_kind":    str,
  "related_ref":     dict | None,
  "url":             str,
  "body":            str,  # optional; some helpers only
}
```

`_normalise_existing_item` (`:1032-1059`) then adds `source_type` + `occurred_at` + `summary` + `detail` + `actor` + `id` to produce the final response item.

### 1.d · Legacy item shape (what `_dispatch_to_item` + `_audit_to_item` return)

Different field names:
- `type` (not `kind`) ∈ sms / email / job_edited / payment
- `occurred_at` (set directly, not derived via `_normalise_existing_item`)
- `actor_label` + `actor_kind` + `actor_user_id` (three fields, not nested in `actor`)
- `direction` (inbound / outbound / internal)
- `channel_id` (= row `id`; no modern equivalent)
- `body_preview` (not `body`)
- `delivery_status` + `delivery_error`
- Event-specific fields: `job_id` / `fields_changed` / `invoice_recalculated` / `invoice_id` / `amount_cents` / `payment_intent_id` / `bulk_run_id` / `via_impersonation`

**Shape delta is material** — direct lift of legacy helpers into `_build_full_timeline` would produce heterogeneous items that break `_normalise_existing_item` + `_dedupe_by_ref`'s `ref_type` convention + the FE renderers' field expectations.

### 1.e · `_build_full_timeline` plug-in surface

`_build_full_timeline` (`:1091-1152`) composes 7 source helpers today (role-gated: 4 for all admins + customer portal, 3 more for admin/super_admin only via `_FULL_TIMELINE_ROLES`). After `_normalise_existing_item` runs over every item, `_dedupe_by_ref` deduplicates by `(ref_type, ref_id)` and suppresses `invoice`/`estimate` raw rows when a `marketing_delivery` already surfaced the same ref.

Natural plug-in point for the new sources: before `_normalise_existing_item` runs (same pattern as existing helpers). Gating depends on §5 operator decision.

---

## 2 · Shape-adapter approach — two forks

### 2.a · Fork (a) · Wrap

Keep `_dispatch_to_item` + `_audit_to_item` verbatim. Add thin wrapper functions `_dispatch_log_to_items(customer, tenant_id, wanted_kinds, from_iso, to_iso, role)` and `_audit_events_to_items(customer, tenant_id, wanted_kinds, from_iso, to_iso, role)` that:

1. Query `notification_dispatch_log` / `audit_events` with legacy filter shapes.
2. Call `_dispatch_to_item` / `_audit_to_item` on each row.
3. **Rewrite the result** to Phase-B shape (map `type` → `kind`, `body_preview` → `body`, pack `actor_*` into `actor` object, strip `channel_id`, retain event-specific fields under `detail`).
4. Return a list of Phase-B items.
5. Portal path never gets the admin fields back (helpers emit them, wrapper strips them for `role == "customer"` before Phase-B shape rewrite OR we trust `_strip_admin_fields` applied downstream).

Pros: minimal change to legacy helpers; two preserved helpers remain intact as a canonical reference.
Cons: adapter is a lossy translation layer (two shapes, mapped once); `_dispatch_to_item` + `_audit_to_item` continue to emit the legacy shape nobody else consumes.

Est LOC: ~120-150 (two wrapper fns + mapping dict + tests).

### 2.b · Fork (b) · Rewrite (recommended)

Delete `_dispatch_to_item` + `_audit_to_item`. Write new `_dispatch_log_to_items` + `_audit_events_to_items` that produce Phase-B items directly, following the pattern of `_lead_communications_to_items` (`:911-976`) and `_lead_inbound_sms_to_items` (`:979-1029`).

New helpers emit:
```python
{
  "kind":            "email" | "sms",
  "subject":         ...,
  "template_name":   "",   # notification_dispatch_log doesn't carry this
  "delivery_status": row.status,
  "created_at":      row.sent_at or row.reserved_at,
  "ref_type":        "notification_dispatch" | "audit_event",
  "ref_id":          row.id,
  "recipient":       row.resolved_address,
  "trigger_kind":    "",
  "related_ref":     None,
  "url":             "",
  "body":            metadata.body or metadata.message or subject,
}
```

Audit-event helper handles the 3 event-type branches (`portal_invite_bulk` → `kind=email`, `job_edited_after_completion` → `kind=note` with K6 body text, `invoice_auto_charged` → `kind=note` or new `kind=payment`?) — see §4 for event-type-kind mapping decision.

Pros: single shape, no translation layer; new helpers match the convention of every other Phase-B source; `_normalise_existing_item` + `_dedupe_by_ref` apply uniformly.
Cons: deletes the two preserved helpers (operator's preserve-with-comment default is one-ship inverted); new helpers must separately handle the privacy-strip on admin-only fields OR rely on never emitting them.

Est LOC: ~180-220 (two new helpers + delete two legacy + tests + `_dedupe_by_ref` audit for `ref_type` collisions).

### 2.c · Comparison

| Dimension | Fork (a) Wrap | Fork (b) Rewrite |
|---|---|---|
| LOC | ~120-150 | ~180-220 |
| Legacy helpers | Preserved | Deleted |
| Shape translation layer | Needed (one map) | None |
| Phase-B convention match | Partial (adapter boundary) | Full |
| K6 / K14 branch-specific fields | Nested under `detail` via mapping | Natively in item (per legacy) |
| Mobile parity | Needs mobile `normaliseTimelineItem` to understand the mapped shape | Mobile already handles Phase-B shape |
| Admin-field privacy | Via `_strip_admin_fields` in wrapper | Native (never emit admin fields top-level) |
| Dedupe concerns | Shares `ref_type` namespace via mapping | New `ref_type` values — audit `_dedupe_by_ref` for collisions |

---

## 3 · `_AUDIT_EVENT_TYPES` → Phase-B `kind` mapping

| `event_type` | Legacy `type` | Proposed Phase-B `kind` | Rationale |
|---|---|---|---|
| `portal_invite_bulk` | `email` | `email` | Natural — it IS an email dispatch |
| `job_edited_after_completion` | `job_edited` | `note` | `_normalise_existing_item` maps `note → note` source_type; event is a system-logged internal event, matches `note` semantic |
| `invoice_auto_charged` | `payment` | `note` OR new `payment` | **Operator decision in §4.b.** `note` fits existing shape; `payment` would require extending `_TIMELINE_ALLOWED_KINDS` + FE renderer |

New `_TIMELINE_ALLOWED_KINDS` surface if `payment` is added: `{email, sms, invoice, estimate, call, note, payment}`. `_normalise_existing_item.src` map extends. FE `DefaultRow` + `CommunicationDetailModal` need `payment` branch.

---

## 4 · Operator decisions matrix

### §4.a · Shape-adapter approach

**(a) Wrap** vs. **(b) Rewrite**. Default recommendation: **(b) Rewrite** — matches Phase-B convention, avoids a translation layer, mobile parity is cleaner. The preserved helpers' purpose was always "recoverable primitives for the eventual migration"; the preserve-with-comment default inverts here because the migration is now happening.

### §4.b · `invoice_auto_charged` kind mapping

**(α) Fold into `note` kind** — reuses existing shape + renderer. Loses the structured payment metadata (amount / payment_intent_id / currency) unless retained under `detail`.
**(β) New `payment` kind** — extends `_TIMELINE_ALLOWED_KINDS` + requires FE `DefaultRow` branch + `CommunicationDetailModal` + mobile `normaliseTimelineItem` + a new icon convention. Est +40-60 LOC FE + ~20 LOC BE on top of the base rewrite.

Default recommendation: **(α) note** for the base ship; raise `TD-98-be-sources-payment-kind (P3)` candidate for (β) if operator wants it later.

### §4.c · `delivery_error` fate

**(x) Preserve inline on each item** — add `delivery_error` field to Phase-B item shape (admin only, strip in portal path via `_strip_admin_fields`). FE renderers need a conditional error badge; mobile already has `normaliseTimelineItem.deliveryError` + admin render per the mobile track note.
**(y) Separate `delivery_metadata` object** — cleaner nested shape; items only carry it when a delivery context exists. Requires schema decision on FE: shared `detail.deliveryError` under existing detail object OR a new sibling.
**(z) Drop entirely** — document as intentional loss. Mobile's existing `deliveryError` render becomes dead code pending mobile cleanup (TD-98-mobile-detail scope).

Default recommendation: **(x) inline** — mobile is already shaped for it; the `_strip_admin_fields` pattern handles portal privacy; FE conditional badge is a small addition.

### §4.d · Portal visibility (`/customers/me/timeline`)

| Source | Operator sub-decision |
|---|---|
| `notification_dispatch_log` | Likely **YES** — customer's own transactional notifications are the strongest portal fit; strip `actor_user_id` + `delivery_error` via existing pattern. |
| `audit_events::portal_invite_bulk` | **Operator call** — customer DID receive the email, so arguably visible; but surfaces admin bulk-operation framing. Default: **NO** (admin-only). |
| `audit_events::job_edited_after_completion` | **NO** — K6 privacy constraint ("never leaks before/after values") already applies; the row itself is admin provenance. Default: **admin-only**. |
| `audit_events::invoice_auto_charged` | **Operator call** — customer was auto-charged on their card; arguably visible with amount but no admin provenance. Default: **portal-visible with `actor_user_id` + `via_impersonation` stripped**. |

Default recommendation: **split surface** — `notification_dispatch_log` AND `invoice_auto_charged` show on portal (with field-strip); other 2 audit event types admin-only.

### §4.e · Test coverage depth

**(1) Minimal** — 1 pytest with mixed-source fixture asserts dispatch + audit rows interleave chronologically with existing sources; tenant isolation smoke. ~90-120 LOC.
**(2) Full matrix** — 1 pytest per source × portal/admin × field-strip × dedup × tenant. ~250-350 LOC.

Default recommendation: **(2) Full matrix** — scope is history-preservation; regression surface is wide; P2 priority justifies thorough coverage.

---

## 5 · Tenant isolation + privacy posture

- Both legacy query shapes already carry `tenant_id` as the top-level predicate — tenant leak is NOT a blocker.
- `_strip_admin_fields` logic in Fork (a) applies via `role` check in wrapper. In Fork (b), new helpers simply never emit `actor_user_id` + `delivery_error` top-level unless `role in _FULL_TIMELINE_ROLES`.
- Portal path in `_build_full_timeline` currently has NO explicit strip call — the design relies on each helper not emitting admin fields in the first place (verified by inspection of `_lead_communications_to_items` + `_marketing_deliveries_to_items`). New helpers must follow this convention OR we re-introduce `_strip_admin_fields` into the `_paginated_timeline_response` path for the customer branch.

**Blocking item for Fork (b):** new helpers MUST emit admin fields only when `role in _FULL_TIMELINE_ROLES` to match Phase-B convention. Implementation detail, not a design question.

---

## 6 · Mobile follow-up

- Mobile `normaliseTimelineItem.deliveryError` already exists and renders for admins (per TD-98-be-cleanup-mobile audit `td98_be_cleanup_mobile_audit.md:77`). No mobile change needed if §4.c (x) is picked.
- If §4.b (β) is picked (new `payment` kind), mobile needs `normaliseTimelineItem` extension + render branch — raise as `TD-98-be-sources-mobile-payment (P3)` candidate alongside the web `TD-98-be-sources-payment-kind` candidate.
- Mobile's `TD-98-mobile-detail` (P3) candidate inherits any new kinds that need a detail sheet — surface the new `kind` values in that candidate's scope note once this ship lands.

---

## 7 · Test matrix proposal (if §4.e (2) picked)

### 7.a · pytest (new file `test_td98_be_sources_notification_dispatch_log.py` + `test_td98_be_sources_audit_events.py`)

**File 1 — `notification_dispatch_log` reader**:
1. SMS + email dispatch rows surface on admin timeline with correct `kind` + `delivery_status`.
2. `recipient_id` match AND `resolved_address` match both work; union via `$or` doesn't double-count.
3. Tenant isolation — cross-tenant dispatch rows never leak.
4. Portal path (`/customers/me/timeline`) sees dispatch rows but NOT `actor_user_id` / `delivery_error`.
5. `kind` filter (`?kind=email`) scopes correctly.
6. `from` / `to` date-range composes.
7. Hard-cap at `_TIMELINE_HARD_CAP` = 500.

**File 2 — `audit_events` reader**:
1. All 3 event types surface on admin timeline with correct derived `kind`.
2. `payload.customer_id` + `payload.customer_ids` both match; union doesn't double-count.
3. Tenant isolation.
4. Portal path — per §4.d operator picks; test asserts the chosen matrix.
5. Field-strip on `invoice_auto_charged` for portal (if picked).
6. K6 `job_edited_after_completion` never leaks `before`/`after` field values (existing invariant must hold).

**Integration file (optional, `test_td98_be_sources_integration.py`)**:
1. Mixed-source fixture interleaves dispatch + audit + marketing + lead_communications correctly by `occurred_at DESC`.
2. Dedupe doesn't drop legitimate dispatch rows (`ref_type="notification_dispatch"` is new — assert no collision with marketing).
3. Admin vs portal field-strip holds across the full merge.

### 7.b · vitest (optional, only if §4.c (x) adds a FE badge)

Thin test confirming `delivery_error` badge renders on admin timeline + is absent on portal timeline. ~40 LOC.

---

## 8 · Ship plan (deferred to operator approval)

Expected 2-3 atomic commits depending on Fork + decisions:

- `td98-be-sources-be` · new helpers + `_build_full_timeline` wiring + delete legacy helpers if Fork (b) + pytest suite.
- `td98-be-sources-fe` (optional) · FE `delivery_error` badge + `CommunicationDetailModal` branch if `payment` kind added + vitest.
- `td98-be-sources-doc` · TECH_DEBT.md CLOSED entry + close `_load_dispatch` doc-drift + raise mobile follow-up candidates + commit_log iteration if applicable.

Est total LOC: Fork (a) ~180-250, Fork (b) ~260-350 (+ FE deltas if §4.b (β) or §4.c (x)).

---

## 9 · Pre-audit grep protocol receipt

- **Step 1 memory grep**: hits on `memory/TECH_DEBT.md`, `memory/mobile/td98_be_cleanup_mobile_audit.md`, `memory/td98_99_combined_communication_timeline_audit.md` all reference TD-98-be-sources as the known candidate; **no existing audit doc covers the scope** — this is the first.
- **Step 2 file-inventory recon**: `_dispatch_to_item` + `_audit_to_item` present + preserved per TD-98-be-cleanup-retire comment; `_load_dispatch` referenced in a comment only (minor doc drift to fix in ship doc commit); no helper reads `notification_dispatch_log` or `audit_events` into Phase-B pipeline on either web OR mobile track.
- **Step 3 source enumeration** (per `td-lessons-doc-3`): the two legacy collections + the `delivery_error` field; three source axes to restore. No hidden source dependencies surfaced.
- **Default-stance applied**: assume shipped until recon disproves. Recon disproved — this ticket IS genuinely open work.

**Clean recon finding** per `td-lessons-doc-4` codification: "clean recon is now the exception, not the default." Noted as a surprise finding in this audit's headline.

---

## 10 · STOP · Operator decisions required

Before any BE/FE ship:

1. **§4.a — Shape-adapter approach**: Fork (a) wrap OR Fork (b) rewrite. Recommended: **(b) rewrite**.
2. **§4.b — `invoice_auto_charged` kind**: (α) note OR (β) new `payment` kind. Recommended: **(α) note** base ship; raise `TD-98-be-sources-payment-kind (P3)` for (β) later.
3. **§4.c — `delivery_error` fate**: (x) inline OR (y) nested OR (z) drop. Recommended: **(x) inline** with portal strip.
4. **§4.d — Portal visibility matrix**: 4 sub-decisions on which audit event types surface on `/customers/me/timeline`. Recommended: **split** (dispatch_log + invoice_auto_charged portal-visible; portal_invite_bulk + job_edited admin-only).
5. **§4.e — Test coverage depth**: (1) minimal OR (2) full matrix. Recommended: **(2) full matrix**.

Pattern-strength callout updated: this is the **first clean-recon finding since the default-stance shift** (0 of 1 post-shift audits carry a framing-vs-reality delta; prior 6 of 7 or 83% did). Monitor whether default-stance shift reduces delta rate across subsequent audits.
