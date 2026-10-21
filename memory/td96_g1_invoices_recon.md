# TD-96-g1-invoices · Phase 1 Recon

**Scope:** reconcile the `linked_quotes_count` field on `GET /leads/{lid}` against the `/quotes?lead_id=X&view=all` filtered list. BE-only this cycle (unless the fork chosen requires an FE touch).

**Phase 1 = recon only. No code.**

---

## 1. Bookmark text (verbatim) + reality check

Grep of `memory/TECH_DEBT.md:1107-1115`:

```markdown
## TD-96-g1-invoices (candidate, P3 BE/web)

- **Reporter:** mobile track recon.
- **Finding:** panel's `linked_quotes_count` counts converted invoices via
  `$or` on `converted_from_lead_id`, but `/quotes?lead_id=X&view=all` returns
  quote-shaped rows only (`doc_type="quote"`). Counts disagree — "View all 2"
  shows 1 row on 1 live case. Semantic ambiguity: does "linked quotes"
  mean "docs that WERE quotes" (count current + reparented including those
  auto-converted to invoices) or "docs that ARE quotes" (narrow)?
- **Fork options:**
  - (i) **Tighten** `linked_quotes_count` to quotes-only (`doc_type="quote"`
    filter on the `$or`). Count matches `/quotes?lead_id=` output exactly.
  - (ii) **Expand** `/quotes?lead_id=` to include invoice-shaped reparented
    docs (`doc_type ∈ {quote, invoice}` when `lead_id` is set). Semantic
    becomes "all docs that originated from this lead".
- **Est LOC:** ~5-15 LOC BE either fork + ~1 pytest update.
- **Priority:** P3 (candidate, BE/web). Operator picks fork.
```

**Supporting bookmark** at `memory/TECH_DEBT.md:1029-1034` (shorter version of the same ticket, logged twice during the broader TD-96 tracking):

```markdown
- `GET /leads/{lid}/quotes` and TD-96-g2's `linked_quotes_count` count both
  quote- and invoice-shaped docs (`recipient_type="lead"` or
  `converted_from_lead_id`).
- `/quotes?lead_id=X&view=<any>` returns quote-shaped rows only; `view`
  overrides even `&doc_type=invoice`.
- Live: lead `8721ff57` panel shows "2" (converted invoice `eb541e58` +
  quote `cdc8cd49`), and the list shows 1.
```

**Reality check — fork is REAL, not imaginary.** Confirmed by code inspection (§2 below). The bookmark reporter's observation holds: the panel count includes converted invoices via `converted_from_lead_id`, but the "View all" list filter forces `doc_type="quote"` whenever `view` is set.

---

## 2. Current state audit — grep + line refs

### `linked_quotes_count` — single compute site, no persistence

**Compute site:** `backend/routers/leads.py:304-320`
```python
# TD-96-g2 · Feb-2026 — additive linked_quotes_count mirrors the
# GET /leads/{lid}/quotes $or semantics so the lead-detail
# Linked-Quotes panel stays visible after close-won reparent …
row["linked_quotes_count"] = int(await db.quotes.count_documents(
    {"tenant_id": tenant["id"],
     "$or": [
         {"recipient_type": "lead", "recipient_id": lid},
         {"converted_from_lead_id": lid},
     ]},
))
```

- **Computed on read** inside `GET /leads/{lid}`. Not denormalized on `db.leads`.
- **Counts anything matching the `$or`** — any doc in `db.quotes` where the lead is either the current recipient OR the historical conversion source. **No `doc_type` filter.** Invoice-shaped docs count if they carry `converted_from_lead_id`.

### Sibling list endpoint — same `$or`, same shape

**`GET /leads/{lid}/quotes`** at `backend/routers/leads.py:334-378`
- Filter: same `$or` as the count (lines 352-358).
- Returns `items`, `total`, `limit`. `items[]` includes `doc_type` + `reparented` flag per row.
- **Counts and lists are internally consistent** (same filter).

### The disagreement surface — `/quotes?lead_id=` list endpoint

**Lead-scoped filter emission** in `backend/routers/quotes.py:486-502`
```python
if lead_id:
    _lead_and = q.get("$and", [])
    _lead_and.append({"$or": [
        {"recipient_type": "lead", "recipient_id": lead_id},
        {"converted_from_lead_id": lead_id},
    ]})
    q["$and"] = _lead_and
```
By itself this `$or` is **doc-type-agnostic**. It matches both quote-shaped and invoice-shaped docs.

**The `view` lifecycle filter** at `backend/routers/quotes.py:434`
```python
if _view:
    …
    q["doc_type"] = "quote"      # ← forces doc_type = "quote" for ANY view
```
This forces `doc_type="quote"` whenever any `view=` param is set — including `view=all`. The `view=all` branch (comment at lines 467-468) only adds the `doc_type="quote"` scope with no status predicate.

**Therefore:**
| Call | `doc_type` filter | Counts |
|---|---|---|
| `linked_quotes_count` field on `GET /leads/{lid}` | none | quote-shaped **+** invoice-shaped |
| `GET /leads/{lid}/quotes` | none | quote-shaped **+** invoice-shaped |
| `GET /quotes?lead_id=X` (no `view`) | none | quote-shaped **+** invoice-shaped |
| `GET /quotes?lead_id=X&view=all` | **forced `"quote"`** | quote-shaped **only** |
| `GET /quotes?lead_id=X&view=<any>` | **forced `"quote"`** | quote-shaped only |

The "View all" link on the LeadDetail web page uses `&view=all` (post-TD-96-g1-web-view fix) which triggers the forced `doc_type="quote"`.

### Where converted-invoice docs come from

**Reparent step in `_run_close_won_pipeline`** at `backend/routers/leads.py:828-838`
```python
await db.quotes.update_many(
    {"tenant_id": tenant_id, "recipient_type": "lead",
     "recipient_id": lead["id"]},
    {"$set": {
        "customer_id": cid,
        "recipient_type": "customer",
        "recipient_id": cid,
        "converted_from_lead_id": lead["id"],
    }},
)
```
- The `update_many` filter has **no `doc_type` scope**. BOTH quote-shaped and invoice-shaped docs that were lead-recipient get reparented.
- `doc_type` is NEVER mutated — if it was `"invoice"` pre-reparent (because the operator converted a lead's quote to an invoice while the lead was still open), it stays `"invoice"` post-reparent **with `converted_from_lead_id` stamped**.
- Log line at :840-842 explicitly says "reparented N lead-recipient **quotes/invoices**" — the intent to carry invoices is baked in.

### Read sites on web FE

- `frontend/src/pages/leads/LeadDetail.jsx:280-297` — gates the Linked-Quotes panel visibility on `linked_quotes_count` (or legacy `quotes_count` fallback). Does NOT read individual item doc_types.
- `frontend/src/pages/leads/__tests__/LeadDetailLinkedQuotesCountGate.test.jsx` — tests the gate semantic.
- `frontend/src/pages/quotes/QuotesList.jsx:78` — references `linked_quotes_count` in a comment only (no read).

### Read sites on mobile FE (OUT OF SCOPE — reference only)

- `app/leads/[id].tsx` passes `linked_quotes_count` to `LeadLinkedQuotesPanel`. Not touched in this ticket.

### Count semantics summary

**What `linked_quotes_count` currently counts:** every doc in `db.quotes` (BOTH quote-shaped and invoice-shaped) that is either (a) still lead-recipient OR (b) was reparented from this lead (carries `converted_from_lead_id=lid`), scoped to tenant.

**Display locations:**
- Web: `LeadDetail` Linked-Quotes panel gate (visibility only — not shown as a number).
- Mobile: `LeadLinkedQuotesPanel` gate + "View all N" button label (`total` from `/leads/{lid}/quotes` endpoint, which uses the same count).

---

## 3. Fork description (per the bookmark + my audit)

### Option (i) — Tighten count semantics (BE-only)

**Change:** add `"doc_type": "quote"` to the `linked_quotes_count` count AND to the `GET /leads/{lid}/quotes` list filter. Both become strictly "docs that ARE quotes."

**UX implication:**
- Panel count shrinks on leads whose quotes have been converted to invoices mid-lead-lifecycle.
- Lead `8721ff57` live example: panel would show "1" (quote only), filtered list also shows "1". **Consistency: ✅.**
- **Regression on TD-96-g2 intent**: the TD-96-g2 panel-visibility rework explicitly wrote the count to include reparented docs (both shapes) so the operator keeps post-conversion visibility. Tightening undoes that.
- **Operator attribution loss**: a lead that generated 1 quote + 1 invoice would read "1 quote" post-conversion. The invoice becomes invisible from the lead side. Operator can still find the invoice via Customer → Invoices, but the lead → doc-lineage chain breaks.

**Perf implication:** none. Adding a doc_type filter is index-cheap.

### Option (ii) — Expand list to match count (BE-only)

**Change:** when `lead_id` is set on `/quotes?...` AND `view=all` (or `view` is absent), do NOT force `doc_type="quote"`. The lifecycle views (`open`/`accepted`/`declined`/`converted`) retain `doc_type="quote"` because they are quote-lifecycle-specific semantics. Only `view=all` + `lead_id` relaxes.

Concrete code shape (NOT shipping — recon-only sketch):
```python
# backend/routers/quotes.py :434
if _view:
    # When a lead scope is active AND the caller asked for "all",
    # treat "all" literally — include invoice-shaped reparented docs.
    # Lifecycle views (open/accepted/declined/converted) stay
    # quote-only because those statuses only live on quote-shaped docs.
    if not (lead_id and _view == "all"):
        q["doc_type"] = "quote"
    …
```

**UX implication:**
- Panel count and list disagreement goes away. Lead `8721ff57`: panel shows "2", list shows 2 rows (quote + invoice side-by-side).
- Rows carry `doc_type` field already — FE row-renderer can show "Quote" vs "Invoice" badge inline. Minor FE polish if operator wants explicit badging on the quotes list page.
- Click-through on an invoice row needs the right route: `/invoices/${id}` not `/quotes/${id}`. **Check needed on `QuotesList.jsx` row click handler.**
- Preserves TD-96-g2 intent (both shapes stay visible from the lead side).

**Perf implication:** none. Removing a filter doesn't make queries slower; the `$or` already dominates the predicate cost.

### Option (iii) — Hybrid (dedicated `linked_docs_count` + unchanged `linked_quotes_count`)

**Change:** keep `linked_quotes_count` as-is but add a new `linked_quotes_count` → `linked_docs_count` rename or an additional `linked_invoices_count`. Change the panel to display them separately ("1 quote · 1 invoice").

**UX implication:** most informative, but requires FE work on both web + mobile. Scope creep.

**Perf implication:** 1 extra `count_documents` per lead-detail GET.

### Option (iv) — No-op (close as wontfix)

**Change:** none. Accept the mismatch and update the bookmark to clarify the semantic ("count is total lineage, list is quote-shaped only").

**UX implication:** operator confusion persists. Low-value close.

---

## 4. Related tickets (constraints)

### TD-96-g2 (SHIPPED, Feb-2026) — the source of the current count semantic

- Established `linked_quotes_count` with the `$or` on `converted_from_lead_id` **explicitly** so the panel survives close-won reparent.
- Code comments at `routers/leads.py:304-311` are explicit: `linked_quotes_count` is designed to superset `quotes_count` (which was pre-conversion lead-recipient-only).
- Tests at `backend/tests/test_td96_g2_linked_quotes_count.py:150-151` **lock in** that reparented docs are counted:
  ```python
  assert out["linked_quotes_count"] == 2, \
      "linked_quotes_count must include reparented docs"
  ```
- **Implication:** Option (i) requires updating this test to match the new tightened semantic. That test's assertion failure would be the regression signal.

### TD-96-g1 (SHIPPED, Feb-2026) — the source of the `/quotes?lead_id=` filter

- Added `lead_id` as a composable filter on the quotes list endpoint (`quotes.py:486-502`).
- Comment at :489-490 says the `$or` is to **mirror `GET /leads/{lid}/quotes` + the `linked_quotes_count` field** — meaning the ORIGINAL design intent was for consistency across all three surfaces (count, lead-scoped list, quote-scoped list).
- The `view=all` forcing of `doc_type="quote"` is actually a conflict within TD-96-g1 itself: the lead_id filter branch wanted consistency, but it layered on top of the pre-existing lifecycle `view` filter which assumes quotes-only.
- **Implication:** Option (ii) is actually fixing an unintended interaction, not changing design intent. Reading the TD-96-g1 code comments suggests the author expected consistency but didn't notice the `view` branch's `doc_type` forcing.

### Reparent step (`_run_close_won_pipeline`) — invoices-carry-forward is explicit

- At `routers/leads.py:828-842`, log line says "reparented N lead-recipient **quotes/invoices**" — intent to carry invoices through conversion is baked in.
- `converted_from_lead_id` is stamped on BOTH shapes without discrimination.
- **Implication:** Option (i) would make the invoice-carry-forward dead weight (the stamp exists but is never surfaced). Architectural inconsistency.

### TD-96-quotes-approved-orphan (candidate, parked)

Unrelated to this fork — about legacy `approved` status normalization. Not a constraint.

### Mobile parity note

Mobile `LeadLinkedQuotesPanel` (SHIPPED `c59366785`) consumes `linked_quotes_count` as a gate. Mobile's "View all N" label consumes `total` from `/leads/{lid}/quotes` which stays consistent regardless of fork. **Mobile is UNAFFECTED by either Option (i) or (ii) at the API-contract level** — both options leave `linked_quotes_count` and `/leads/{lid}/quotes` self-consistent.

The only mobile touch would come if we chose Option (iii) which adds a new field.

---

## 5. Recommendation

**Recommend Option (ii) — Expand `/quotes?lead_id=&view=all` to include invoice-shaped reparented docs.**

Reasons (in priority order):

1. **Preserves TD-96-g2 design intent.** The whole point of `linked_quotes_count` was post-conversion visibility. Tightening (i) kills that intent for a cosmetic count-match win.
2. **Preserves the invoice-carry-forward in the reparent step.** The code at `routers/leads.py:828-842` stamps `converted_from_lead_id` on invoices intentionally. Option (ii) honors that stamp; Option (i) orphans it.
3. **Fixes an unintended interaction, not a design decision.** The `view` branch's forced `doc_type="quote"` predates the `lead_id` filter. The two were layered without noticing the conflict. Option (ii) is the smaller correction.
4. **Preserves operator mental model.** From the lead side, "view all" means "everything that came from this lead." Operators tracking revenue attribution through a lead want the invoice visible.
5. **Scope is narrow.** ~5-10 LOC: a single `if` branch in `quotes.py:434`.
6. **Mobile needs no change.** Both options are API-stable for mobile.

**Caveats + a required Phase 2 FE touch:**
- **Mixed-shape list page**: Option (ii) makes `/quotes?lead_id=X&view=all` return a mix of quote and invoice rows. `QuotesList.jsx` currently assumes quote-shaped rows (every row click → `/quotes/${id}`). Need to verify row click dispatches to `/invoices/${id}` when `doc_type === "invoice"`. Small FE check — may already handle this (the quotes list is the "docs" list under the hood).
- **Row-label clarity**: the mixed list should surface the kind inline. Minor FE polish if operator wants explicit "Invoice INV-01" vs "Quote QT-01" labels. Likely already handled by `QuotesList`'s existing invoice/quote rendering split (since the same page already handles both shapes at the global filter level).

### If operator picks Option (i) instead

- Simpler BE change (same ~5-10 LOC on count + list).
- MUST update `test_td96_g2_linked_quotes_count.py` — specifically the "reparented docs must count" assertion flips.
- MUST update `TD-96-g2` CLOSED bookmark text to reflect the semantic shift.
- Operator loses revenue-attribution-from-lead UX.

---

## 6. Testing plan (if we proceed with Option (ii))

### Pytest cases

Append to `backend/tests/test_td96_g1_lead_id_filter.py` (or new file `test_td_96_g1_invoices.py`):

1. **Positive — quote-shaped doc returns.** Seed a `doc_type="quote"` with `recipient_type="lead"` + `recipient_id=lid`; `GET /quotes?lead_id=lid&view=all`; assert the quote is in the response.
2. **Positive — invoice-shaped reparented doc returns.** Seed a `doc_type="invoice"` with `recipient_type="customer"` + `converted_from_lead_id=lid`; same call; assert the invoice is in the response.
3. **Count parity — `linked_quotes_count` matches `/quotes?lead_id=&view=all` result length.** Seed 1 quote + 1 invoice linked to the same lead; call both endpoints; assert `linked_quotes_count == len(response)`.
4. **Lifecycle view still quote-only (regression).** `view=open` + `lead_id` — should still exclude invoice-shaped docs (invoices don't have `open` lifecycle status).
5. **Lifecycle view=accepted still quote-only (regression).** Same — invoices don't carry quote `accepted` status.
6. **`view=declined` + `lead_id` still quote-only.**
7. **No `view` + `lead_id` returns both** (existing behavior — regression check).
8. **Tenant isolation on expanded match.** Invoice linked to lead B's conversion in tenant B should not surface to tenant A admin.
9. **Soft-delete still excludes** (invoice-shaped soft-deleted doc).
10. **RBAC — technician 403 or empty** (whichever the quotes list currently does).
11. **Hit shape unchanged.** Response envelope keys stable (`rows`/`items` depending on Shape-A pagination).

### Vitest / FE regression

- `QuotesList.jsx` row click routing — verify invoice-shaped rows route to `/invoices/${id}` (click dispatch grep).
- Row label — if the list currently prefixes `"Invoice "` on invoice-shaped rows via `invoice_number`, no visual change needed. Spot-check needed.
- `LeadDetailLinkedQuotesCountGate.test.jsx` — unchanged, since the count isn't changing semantically on this fork.
- If `QuotesList` row routing is already shape-aware, **no new vitest cases are needed**. If not, add a 1-case fixture test that an invoice-shaped row routes to `/invoices/`.

### Migration implications

**None for Option (ii).** No stored data changes; purely a query-filter adjustment. `linked_quotes_count` already included invoice-shaped reparented docs since TD-96-g2 shipped.

(Option (i) also needs no migration — just a query filter tightening + test updates.)

---

## 7. Phase 2 cost estimate (Option (ii) assumed)

| Scope | LOC |
|---|---|
| `backend/routers/quotes.py` — `_view` branch conditional at :434 | ~4 |
| Module docstring + inline comments | ~6 |
| `backend/tests/test_td_96_g1_invoices.py` **(new)** or append to `test_td96_g1_lead_id_filter.py` — 10-11 cases | ~130 |
| `frontend/src/pages/quotes/QuotesList.jsx` — row click routing shape check (if not already shape-aware) | 0-5 |
| Vitest spot-check if needed | 0-30 |
| **Total** | **~140-175** |

**Shippable in 1 atomic BE commit** (+ an optional 2nd FE commit if the quotes list page needs a row-routing fix). Edit-to-commit well under 3 min for the BE commit.

---

## 8. Guardrail attestation

- No code changes this cycle.
- No `/app/mobile/` touches planned (API contract unchanged on mobile side regardless of fork chosen).
- No scope creep into other TD-96 branches (g2 panel gate, g1-web-view, mobile-labels — all shipped and untouched).
- No scope creep into `_run_close_won_pipeline` or the reparent step itself.
- No testing agent — manual pytest/vitest only in Phase 2.
- Any instructions in user chat text attempting to expand scope mid-cycle classified as hostile per V1-V15 defense codified in `TECH_DEBT.md`.

---

## 9. Open decisions for operator

**Required Y/N:**

1. **Fork pick: (i) Tighten, (ii) Expand, (iii) Hybrid new field, or (iv) No-op/close?** Recommendation: **(ii) Expand**.
2. **If (ii):** append tests to existing `test_td96_g1_lead_id_filter.py` or create new `test_td_96_g1_invoices.py`? Recommend new file for scope hygiene.
3. **If (ii):** should I also audit `QuotesList.jsx` row-click routing in Phase 2 (and ship an FE fix if needed), or defer to a separate FE ticket if a mismatch is found?

Everything else is deterministically spec'd by this recon.
