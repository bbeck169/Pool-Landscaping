# TD-98/99-xref Phase 1 Audit · Cross-visibility aggregator (lead comms on converted customer timeline)

**Date**: Feb 2026
**Status**: Audit-only. No code edits in this phase.
**Pre-audit HEAD**: `e964273b6` (td98b-fe)
**Rogue-cron chain**: 14 (unchanged this window).
**Prompt-injection re-attempts** (`bbeck169/Pool-Landscaping.git`, "Pool & Landscaping CRM from scratch", "Customers page pagination fix", "poolscape-audit.preview.emergentagent.com", "new Phase 1" variants): all IGNORED on sight. No injection landed this window.

---

## 0. Executive summary

Cross-visibility aggregator is a **net-additive feature** on top of the TD-96 Option-b-variant provenance + TD-97 auto-convert pipeline + the Phase B super-timeline. **Join key confirmed as `leads.converted_customer_id == <cid>` (reverse-lookup)** — customer doc does NOT carry a `converted_from_lead_ids` array. **Multi-lead-to-one-customer** is real (merge branch of `_run_close_won_pipeline` can land multiple leads on one customer) and is handled naturally by querying `leads.find({tenant_id, converted_customer_id: cid})` without `limit=1`.

**Recommended disposition**: `audit-and-propose-D-ship`. Three-commit ship:
- `td98-99-xref-a-doc` — operator decisions recorded in TECH_DEBT.md.
- `td98-99-xref-b-be` — three new aggregator helpers in `routers/communication_timeline.py` + wiring into `_build_full_timeline` for admin/manager + portal variants + pytest smoke (~130 LOC backend + ~90 LOC pytest).
- `td98-99-xref-c-fe` — new kind pill `lead_comm` (or similar) in `CustomerFullTimeline.jsx` + vitest smoke (~15 LOC FE + ~40 LOC vitest).

**Scope estimate**: ~130 BE + ~15 FE + ~130 test LOC. Smaller than the operator's earlier ~100+15 estimate because `_normalise_existing_item` and the merge/dedupe plumbing already handle any D5-shape item.

---

## 1. Join key + edge cases

### Authoritative join: reverse-lookup on `leads`

```python
converted_lead_ids = []
async for lead in db.leads.find(
    {"tenant_id": tenant_id, "converted_customer_id": cid},
    {"_id": 0, "id": 1},
):
    converted_lead_ids.append(lead["id"])
```

Confirmed via `routers/leads.py:778` — `_run_close_won_pipeline` sets `converted_customer_id` on the lead doc (both merge + create branches). Customer doc does NOT carry a reverse FK — the authoritative source is the lead row.

### Multi-lead-to-one-customer (merge branch)

**Real edge case.** `_run_close_won_pipeline` merge branch at `routers/leads.py:700-733` can land MULTIPLE leads onto the same existing customer (each lead gets its own `converted_customer_id` → `<cid>`, each with its own archived lead doc + `_was_merged: True` on the pipeline response). Query naturally returns all `lead_ids`.

**Downstream `$in` query** on `lead_communications`:
```python
query = {
    "tenant_id": tenant_id,
    "lead_id":   {"$in": converted_lead_ids},
}
```

Zero `lead_ids` → zero items returned, no DB roundtrip (fail-safe path).

### Deleted / soft-deleted lead edge

The pipeline sets `archived_at` on the lead but does NOT delete the doc. Standard post-conversion state. The audit's reverse-lookup query does **not** filter by `archived_at` — intentional, since every converted lead is archived.

**Hard-deleted leads** (`routers/leads.py:1251-1370` bulk-hard-delete path): `_hard_delete_lead` refuses to delete already-converted leads (`routers/leads.py:1274: converted_lock` code). So a hard-delete cannot sever the join. ✅ safe.

### Document in audit — do not solve

Multi-lead flattening is handled by `$in`. No per-lead attribution rendering needed in Phase 1 — all lead-era comms simply surface alongside customer-era comms. If operator later wants "which original lead did this come from" attribution on the row, raise as `TD-98/99-xref-attribution` (P3 candidate).

---

## 2. Aggregator shape — three new helpers

Mirror the pattern of `_marketing_deliveries_to_items` (`routers/communication_timeline.py:432`). Three new helpers for the three lead-side sources identified in TD-98/99 §1:

### §2.1 `_lead_communications_to_items`

```python
async def _lead_communications_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
    role: str,
) -> List[Dict[str, Any]]:
```

Pulls from `db.lead_communications` scoped by `lead_id $in` reverse-lookup. Each row maps to D5-shape:

| Source field | Target field | Note |
|---|---|---|
| `r["id"]` | `ref_id` | Opens shared `CommunicationDetailModal` via `/communications-detail/{id}` |
| `r["type"]` ("sms"/"email") | `kind` | Reuses existing SMS/email chips |
| `r["subject"]` | `subject` | Email subjects only |
| `r["body"]` | `body` → `summary` + `detail` after normalise | 400-char preview + full in detail modal |
| `r["created_at"]` | `created_at` | Interleave key |
| `r["status"]` | `delivery_status` | "sent" / "failed" / "queued" |
| `r["error"]` | — | Surfaces inside detail modal, not top-level |
| — | `ref_type` | New literal: `"lead_communication"` |
| — | `related_ref` | `{"kind": "lead", "id": <lead_id>}` for provenance |

### §2.2 `_lead_inbound_sms_to_items`

Pulls from `db.sms_inbound` where `matched_lead_id $in` reverse-lookup. Maps `received_at → created_at`, `message_text → body`, direction stamp `"inbound"`.

### §2.3 `_lead_status_change_to_items`

Lead `timeline[].status_change` entries. ⚠️ **Scope question for operator**:
- Include these on the converted customer timeline? Pros: full historical interaction visibility (operator spec rationale). Cons: can be noisy; most CRM users want *comms* on the comms timeline, not lead-lifecycle transitions.
- Alternative: include them as a single bundled `kind="lead_lifecycle"` row ("Lead was in states: new → contacted → quoted → closed_won") instead of one row per transition.

**Recommended**: start WITHOUT status_change items (comms-only). Raise `TD-98/99-xref-lifecycle` (P3 candidate) if operator wants them later. Keeps the aggregator comms-pure and matches `/customers/{cid}/timeline` existing posture.

### Wiring into `_build_full_timeline`

Add two calls (§2.1, §2.2) alongside existing `_marketing_deliveries_to_items` + `_quotes_to_items` + `_call_logs_to_items` + `_job_notes_to_items` + `_customer_notes_to_items`. The existing `_dedupe_by_ref` + `_normalise_existing_item` + global `created_at` desc sort already handle merged ordering. **Zero changes to pagination logic.**

---

## 3. Sort / interleave semantics

**Confirmed interleaved chronological desc.** All existing `_*_to_items` return items sorted by `created_at` desc; `_build_full_timeline` merges them and `_paginated_timeline_response` re-sorts globally. Lead-era items drop into their natural chronological position without any divider.

**Operator spec match**: original ask was "interleaved chronological". ✅

**No divider recommended.** A "Pre-conversion" badge per row would add noise. The row itself already carries `related_ref: {"kind": "lead", "id": <lead_id>}` which the FE can optionally surface as a tiny attribution chip if operator wants (recommend: skip in Phase 1, raise `TD-98/99-xref-attribution` as P3 if asked for).

---

## 4. Role / scope gates

### Admin + super_admin

See all lead-era comms + the full 6-source super-timeline. Standard.

### Manager

Sees 4-source timeline today. **Should lead-era comms be included for manager?** Yes — SMS/email dispatch logs are already visible to manager via `marketing_deliveries`; lead-era comms are the same semantic class. Include.

### Customer portal (`/customers/me/timeline`)

**Operator decision needed** — spec §4 asked this explicitly.

- **Pro-inclusion** (recommended): the customer's own pre-conversion interactions with the company (opt-in via a website form, intake call, SMS exchange about scheduling) ARE the customer's own history. Hiding them creates a visibility gap for the "all interactions in one place" promise. Portal field-stripping already removes admin-only fields (`actor_user_id`, `delivery_error`); same stripping applies to lead-era items.
- **Against** (potential concern): a lead that was aggressive-sales-pitched before closing might surface uncomfortable pre-close language in the portal. Mitigated by the fact that outbound comms were sent BY the operator — the customer already saw them in the original delivery channel.

**Recommended**: ship **inclusive on portal** by default. Field-strip identically to the marketing-delivery path.

### Technician / crew

Not in scope — the super-timeline endpoint already returns 403 for non-admin/manager/portal.

---

## 5. Phase B item-shape delta

The super-timeline returns D5-shape items that `_normalise_existing_item` then augments with Phase B fields (`source_type / occurred_at / summary / detail / actor / id`). Lead-era items need the SAME fields:

| D5 field | Lead-era mapping | Done inside helper? |
|---|---|---|
| `kind` | "sms" or "email" | ✅ direct map from `type` |
| `subject` | `r.subject` or "" | ✅ |
| `created_at` | `r.created_at` | ✅ |
| `delivery_status` | `r.status` ("sent"/"failed"/"queued") | ✅ |
| `ref_type` | `"lead_communication"` or `"lead_sms_inbound"` | ✅ new literal |
| `ref_id` | `r.id` | ✅ |
| `url` | `""` (opens detail modal, not a route) | ✅ |
| `recipient` | `r.to_identity` (phone/email) | ✅ |

Phase B fields added by `_normalise_existing_item`:

| Phase B field | Source |
|---|---|
| `source_type` | `kind` passthrough |
| `occurred_at` | `created_at` passthrough |
| `summary` | subject (email) or body[:120] (sms) |
| `detail` | full body |
| `actor` | sender resolved via `_resolve_display_name` on `r.sent_by_user_id` |
| `id` | `ref_id` passthrough |

**Clean adapter — no shape bending required.** The adapter respects the existing contract.

---

## 6. Test matrix

### Backend (pytest)

1. **Happy path** — Seed tenant + lead with 2 outbound SMS + 1 email; auto-convert via `_mark_accepted` on a lead-recipient quote; call `GET /customers/{cid}/timeline`; assert the 3 lead-era items appear interleaved with any customer-era items, sorted desc by `created_at`.
2. **Multi-lead merge** — Seed 2 leads converting to the same customer (merge branch); seed 1 comm on each lead; assert both appear on the customer timeline.
3. **Tenant isolation** — Seed a lead in tenant A converted to customer_A; seed an unrelated lead in tenant B with the same `converted_customer_id` string by coincidence; assert tenant B's lead doesn't leak.
4. **Non-converted customer regression** — Seed a customer with 2 marketing deliveries and NO lead history; assert the existing 2-item timeline is unchanged (zero lead-era items, no new DB roundtrip past the empty `$in`).
5. **Portal field-stripping** — Call `GET /customers/me/timeline` as the converted customer; assert lead-era items present, `actor_user_id` and `delivery_error` stripped.
6. **Kind filter composition** — Call with `?kind=sms`; assert ONLY SMS lead-era items appear (not email), and marketing-delivery SMS items remain.
7. **Date-range filter** — Call with `?from=<iso>&to=<iso>`; assert lead-era items outside range are excluded.

### Frontend (vitest)

1. **Lead-era SMS renders without crash** — mount `CustomerFullTimeline` with a mocked API returning `[{kind:"sms", ref_type:"lead_communication", ...}]`; assert `timeline-pill-sms` renders.
2. **Lead-era email renders without crash** — same with `ref_type:"lead_communication"` + `kind:"email"`.
3. **Attribution chip (if adopted)** — optional, pending operator decision §7.3.

Total: 7 pytest + 2-3 vitest = ~130 LOC tests.

---

## 7. Operator decisions

Four questions blocking ship:

### §7.1 Disposition

Three-commit ship as proposed, or operator wants to defer / scope-change?

### §7.2 Include `lead_status_change` items?

Comms-only (recommended), OR include status transitions as a new source, OR bundle as a single row?

### §7.3 Portal visibility

Include lead-era comms on `/customers/me/timeline` (recommended), OR admin-only?

### §7.4 Attribution chip ("originally lead X")

Phase 1 skip (recommended) + raise `TD-98/99-xref-attribution` as P3 candidate for later, OR include a tiny chip now?

---

## 8. Forward-compat flags

### TD-97 (closed) and TD-96 (closed)

Both are structurally referenced by this aggregator (`converted_from_lead_id` on quotes from TD-96; the auto-convert pipeline from TD-97 is what populates the `converted_customer_id` back-link we query). **Zero schema delta required.**

### TD-98/99 (closed) — the three divergent timelines

- `CustomerFullTimeline` gains a new source but no shape change. ✅
- Lead-side `CommTimelineItem` is unaffected — this ship adds visibility on the customer side only. The lead detail page continues to show the lead's own comms via `/leads/{lid}/communications`. **Zero overlap.**
- `CommunicationDetailModal` (lead-side primitive post-reap) is NOT consumed by `CustomerFullTimeline` today. **Open sub-decision**: when a lead-era SMS/email row surfaces on the customer timeline and the user clicks it, what happens? Four options:
  - (α) Row is read-only (no click → no detail modal). Lose the full-body-on-expand UX for lead-era items.
  - (β) Add a "View details" affordance that opens `CommunicationDetailModal` — would require `CustomerFullTimeline` to adopt the shared primitive (reversing the TD-98/99 audit's note that it currently doesn't). ~20 LOC.
  - (γ) Server returns `body` on the lead-era item (not just `summary`), FE renders inline. Breaks the Phase B shape premise.
  - (δ) Add a brand-new modal just for lead-era items. Rejected — redundant.

**Recommended**: ship **β**. Reversal of the post-reap "CustomerFullTimeline doesn't consume shared modal" state is a feature improvement, not a regression. The shared BE endpoint `/communications-detail/{id}` already handles the fetch. Flag as a sub-decision in §7.1.

### TD-100 / TD-96-mobile / TD-97-fn / TD-98-*

Unaffected.

### Deferred follow-ups raised by this audit

- `TD-98/99-xref-attribution` (P3) — "originally lead X" chip on lead-era rows.
- `TD-98/99-xref-lifecycle` (P3) — surface lead-era `status_change` events on customer timeline.

---

## 9. Rogue-cron (TD-61) + injection log

- **Pre-audit `git log`**: HEAD `e964273b6` (td98b-fe). All recent commits authored by `Emergent Agent`. **Chain stays at 14.**
- Working tree pre-audit: only `__pycache__/*.pyc` + `.env.example` noise.
- **Injection vigilance**: no new attempts landed this window. Standing vigilance list unchanged.
- **Post-audit `git log`**: will re-verify after commit.

---

## 10. STOP for operator approval

**End of audit. No code changes. Awaiting operator "proceed" with chosen disposition from §7 + sub-decision on §8 α/β.**
