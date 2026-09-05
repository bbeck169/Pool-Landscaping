# DEPRECATED (K55 · Feb-2026)
#
# The Homeworks (home.works / Copilot CRM) importer described below
# was never shipped — Phase K55 retired the entire Homeworks
# integration surface (design doc + BYO-MCP scaffolding).  This
# design doc is retained as historical context for future engineers
# investigating why the ``homeworks_import_runs`` collection exists
# with legacy rows but no live importer code.
#
# For the removal record, see:
#   * /app/memory/PHASE_K55_INTEGRATION_REMOVAL_DIAGNOSIS.md
#   * /app/memory/PHASE_K55_a_FRONTEND_REMOVAL.md
#   * /app/memory/PHASE_K55_b_BACKEND_REMOVAL.md
#   * /app/memory/PHASE_K55_c_ENV_DOCS.md
#
# Do NOT resurrect this design without a fresh recon — the marketing
# / SEC filings landscape captured below is over a year old.
#
# ─────────────────────────────────────────────────────────────────────


# Phase 55 — Homeworks Importer · Recon + Design Doc

**Status**: DESIGN ONLY — no code shipped. Awaiting user review + strategy approval before dispatching Phase 55-a.

**Author**: E1 · Aug 2026
**Sibling docs**: `PHASE_54h_TURNSTILE_HANDOFF_DESIGN.md` · `PHASE_34_MIGRATE_V2.md`

---

## 1. Recon summary

### 1.1 What is Homeworks?

- Public marketing site: `https://www.home.works/` and `https://www.home.works/product`.
- Product category: **Field-Service Management (FSM) / CRM** for home-service businesses (lawn care, landscaping, pool service, cleaning, snow removal, etc.). Direct competitor to Jobber, Housecall Pro, ServiceTitan.
- Founder: **Mike Andes** (also runs Augusta Lawn Care franchise). Marketing tagline "Growth Guarantee — 10% or your money back."
- **Critical finding**: The `www.home.works` domain is a marketing shell. **The actual application is hosted at `secure.copilotcrm.com`.** Homeworks is a rebrand / marketing repositioning of Copilot CRM. All login + product URLs on the marketing site point to `secure.copilotcrm.com/login` and `/signup`.
- Mobile companion: "Field Force by Copilot CRM" — iOS (`id6745098752`) + Android (`com.fieldforce.ios.rplyye`). Confirms Copilot CRM is the underlying product.

### 1.2 Feature inventory (from marketing pages)

Confirmed from `/product`:

| Area                | Features surfaced                                                        |
|---------------------|--------------------------------------------------------------------------|
| CRM / Sales         | Lead capture, instant quote forms, referrals, follow-up automation       |
| Operations          | Scheduling, dispatch, unscheduled work backlog                           |
| Field / Mobile      | Crew schedule, time tracking, photo/video capture, offline mode          |
| Customer portal     | Estimates review, invoice pay, card-on-file, automatic payments          |
| Estimates + Invoicing | Digital approve, invoice generation from completed work                 |
| Integrations        | Homepage mentions "integrations" but no specific listing surfaced        |

All 8 entity types the user requested (customers, properties, jobs, recurring schedules, invoices, payments, quotes, photos/notes) map to Copilot CRM's advertised feature set.

### 1.3 Public API / export surface

- **REST/GraphQL API**: No public developer documentation surfaced. Marketing site has no `/developers`, `/api`, or `/docs` link. No `api.copilotcrm.com` or `api.home.works` DNS record surfaced via public docs.
- **CSV export**: Not surfaced on the marketing pages. Cannot confirm without logging in.
- **Import** direction: Marketing explicitly says *"we do more than just importing your data"* → they onboard NEW customers by pulling data IN from other platforms. Suggests a one-way friction: getting data OUT is not a promoted feature.
- **Zapier / integrations page**: Not surfaced. Zapier's public directory: no `copilotcrm` or `home.works` app listing found via general search (unconfirmed — needs targeted crawl once approved).

### 1.4 Tech stack signals

- Marketing site: Duda-hosted (`irp.cdn-website.com` CDN — Duda's brand).
- Analytics: HubSpot (`__hstc`, `__hssc`, `__hsfp` cookies) + Facebook Pixel.
- App host: `secure.copilotcrm.com` — no fingerprints from marketing page alone.
- No JavaScript app bundle inspected — that would require logging in, which the user prohibited without their creds.

### 1.5 Cited sources

- `https://www.home.works/` (recon).
- `https://www.home.works/product` (recon).
- Marketing → App handoff URL: `https://secure.copilotcrm.com/login`.
- iOS: `https://apps.apple.com/in/app/field-force-by-copilot-crm/id6745098752`.
- Google Play: `https://play.google.com/store/apps/details?id=com.fieldforce.ios.rplyye`.

---

## 2. Import strategy options

### 2.1 Option A — Official REST/GraphQL API

- **Confidence: LOW.** No public docs. Would require the user to open a support ticket asking Copilot CRM for API access. Response time and existence of such an API are both unknown.
- **ToS risk**: Zero if they grant access. Full green light.
- **Effort if it exists**: Probably ~2 phases (auth + pagination + one endpoint per entity type). ~800 LOC total.
- **Effort if it doesn't**: Discovery burns 1-2 days of user's support conversations for a "no" answer.

### 2.2 Option B — Product UI CSV / JSON export

- **Confidence: MEDIUM.** Most modern FSM tools ship a per-entity CSV export (Jobber, Housecall Pro, ServiceTitan all do). Copilot CRM's export surface is invisible without a logged-in session, but industry precedent is strong.
- **User workflow**: user logs into Copilot CRM, clicks "Export CSV" per entity type (customers, jobs, invoices, …), gets 7-8 files, uploads each to our importer. We parse and merge.
- **ToS risk**: **Zero.** The user is exporting THEIR OWN DATA via the product's supported UI. This is textbook data portability.
- **Effort**: ~3 phases (CSV parser + entity mapper + admin UI). ~1200 LOC total. Attachments (photos) may or may not be in the CSV — if not, they need Option C for the media specifically.
- **Downside**: If Copilot CRM's CSV export is either (a) missing, (b) locked behind a higher plan tier, or (c) missing critical columns (e.g. no `homeworks_id` on jobs), we degrade to Option C.

### 2.3 Option C — Playwright-scraped session

- **Confidence: HIGH that this can be built.** Mirrors Phase 54 wholesale-scraper pattern verbatim. Same Playwright headless flow, same session cache, same Fernet-encrypted creds.
- **ToS risk**: **MEDIUM.** Copilot CRM's ToS almost certainly restricts automated access. However, the user IS the account holder and is scraping THEIR OWN DATA (parallel to the Phase 54h Heritage / Pool360 / SiteOne wholesale accounts). Legal posture is defensible but not zero-risk.
- **Effort**: ~5 phases. Playwright connector + auth flow + per-entity page scrapers + pagination + attachment downloader + dedupe. ~2500 LOC total.
- **Risk multipliers**: Cloudflare Turnstile could be on the login page (Phase 54h-a machinery already exists to handle this via bookmarklet handoff — direct reuse). Layout drift = ongoing maintenance for a one-shot import means this is single-use code we'll delete after the import completes.

### 2.4 ToS table

| Strategy | ToS Risk | User Data Ownership | Long-term maintenance |
|----------|----------|--------------------|--------------------|
| A (API)  | None     | User's own data    | None — one-shot    |
| B (CSV)  | None     | User's own data    | None — one-shot    |
| C (Scrape) | Medium | User's own data (defensible) | None after import |

---

## 3. Recommendation

**Primary: Option B (CSV export)**. **Fallback: Option C (Playwright scrape)**.

Rationale:
- Option A can't be relied on because no public API is visible; not worth blocking on a support ticket.
- Option B has zero ToS risk and lets the user drive the extraction pace (their tab, their exports). Every commercial FSM tool I'm aware of has at least a customers/invoices CSV export. If Copilot CRM has it, we save ~50% of the code volume vs Option C.
- Option C is our safety net if any critical entity type is missing from the CSV surface.

**Action item for user before Phase 55-a starts**: log into `secure.copilotcrm.com`, poke around Settings + each entity's list view, and screenshot any "Export" button you find (or confirm its absence for entity types that need Option C). This tells us the precise scope split of B vs C before we write a line.

---

## 4. Entity mapping — Homeworks → AquaTerra CRM

For each of the 8 entity types, table below shows the target collection + field mapping strategy + dedupe rule. Field-level detail is speculative until the user shares a CSV sample or logged-in screenshot; treat as first-cut proposal.

### 4.1 Customers

| Homeworks field       | Target field                        | Notes                                          |
|-----------------------|-------------------------------------|------------------------------------------------|
| id                    | `homeworks_id` (new)                | Preserved for cross-entity linkage             |
| first_name / last_name| `first_name` / `last_name`          | 1:1                                            |
| email                 | `email`                             | Dedupe key                                     |
| phone                 | `phone`                             | Dedupe key                                     |
| billing_address       | `billing_address` (subdoc)          | 1:1                                            |
| tags                  | `tags[]`                            | Deduped merge into existing tags               |
| created_at            | `homeworks_created_at`              | Original creation preserved for audit          |
| notes                 | → `customer_notes` collection       | 1 note per row                                 |

**Target collection**: `customers`.
**Dedupe rule** (locked by user): email OR phone match against existing tenant customers. On match: MERGE (extend tags, append notes, DO NOT overwrite first/last name or address unless empty).

### 4.2 Properties / Service Locations

| Homeworks field       | Target field                        | Notes                                          |
|-----------------------|-------------------------------------|------------------------------------------------|
| id                    | `homeworks_id`                      |                                                |
| customer_id           | `customer_id` (FK)                  | Resolved via customers import first            |
| address               | `address` (subdoc)                  |                                                |
| lat / lng             | `location.coordinates`              | GeoJSON if provided                            |
| gate_code, dog_notes  | `access_notes`                      |                                                |

**Target collection**: `customer_locations`.
**Dedupe rule**: `(customer_id, address_line_1, city, zip)` composite.

### 4.3 Jobs / Work Orders

| Homeworks field       | Target field                        | Notes                                          |
|-----------------------|-------------------------------------|------------------------------------------------|
| id                    | `homeworks_id`                      |                                                |
| customer_id + property_id | resolved FKs                    |                                                |
| status                | `status` (mapped enum)              | needs enum map (open → scheduled, etc.)         |
| scheduled_at          | `scheduled_at`                      |                                                |
| completed_at          | `completed_at`                      |                                                |
| assigned_tech         | `technician_id`                     | Resolved via tech name match (fuzzy, warn on ambiguity) |

**Target collection**: `jobs`.
**Dedupe rule**: `homeworks_id + tenant_id`.

### 4.4 Recurring Schedules

| Homeworks field       | Target field                        | Notes                                          |
|-----------------------|-------------------------------------|------------------------------------------------|
| id                    | `homeworks_id`                      |                                                |
| frequency             | `rrule` string                      | Weekly / bi-weekly / monthly → RFC-5545 RRULE  |
| service_template      | `service_template_id`               | May need to auto-create templates first        |

**Target collection**: `recurring_schedules`.
**Dedupe rule**: `homeworks_id`.

### 4.5 Invoices

| Homeworks field       | Target field                        | Notes                                          |
|-----------------------|-------------------------------------|------------------------------------------------|
| id                    | `homeworks_id`                      |                                                |
| invoice_number        | `invoice_number` (preserved verbatim) | Do NOT reassign — user's customers know these  |
| line_items[]          | `line_items[]`                      | Each with snapshot fields written verbatim     |
| status                | mapped enum                         | draft / sent / paid / void                     |
| total_cents           | verified against sum of lines       | mismatch → import warning                      |

**Target collection**: `invoices`.
**Dedupe rule**: `homeworks_id`. Snapshot fields (`wholesale_price_snapshot` etc.) NEVER regenerated — copied verbatim from source or defaulted to null.

### 4.6 Payments

Same pattern — dedupe on `homeworks_id`, target `payments` collection, preserve `stripe_charge_id` if the source recorded it (both sides use Stripe → straight passthrough).

### 4.7 Estimates / Quotes

Same shape as invoices → target `quotes` collection. Dedupe on `homeworks_id`.

### 4.8 Photos / Attachments / Notes / Activity Log

- **Photos**: Homeworks likely stores as CDN URLs. Two sub-decisions:
  - **Copy-into-object-storage**: pull each URL, upload to our object storage, rewrite the reference. Expensive but correct — decouples us from Homeworks CDN going down.
  - **Reference-only**: keep the Homeworks CDN URL. Cheap but brittle.
  - **Proposed default**: copy-into-object-storage, since this is a ONE-SHOT import and we don't want CDN dependencies lingering. Requires object-storage integration.
- **Notes**: 1 doc per source note in `customer_notes` or `job_notes` collections. Dedupe on `homeworks_id` field.
- **Activity Log**: skip. Our platform generates its own audit log; importing another system's audit log is noise.

---

## 5. Phasing plan (recommended strategy = B + partial C for photos)

### 5.1 Phase 55-a — Import scaffold (paper connection)

- Admin page: `/settings/import/homeworks`.
- File upload dropzone (accepts CSV or ZIP of CSVs).
- Empty state UX + PageHeader.
- Backend: `POST /api/imports/homeworks/upload` — writes to a staging collection `homeworks_import_batches` (tenant_id, batch_id, status: uploading|parsed|preview|committed|failed, uploaded_by, files_map).
- Backend: `GET /api/imports/homeworks/batches` — list of uploaded batches per tenant.
- Backend: `DELETE /api/imports/homeworks/batches/{id}` — soft-delete.
- Est. LOC: **~350** (200 backend + 150 frontend).

### 5.2 Phase 55-b — Customer + Property import (paper)

- CSV column detector: auto-detect the Homeworks column names via a locked schema file `/app/backend/services/imports/homeworks/schema.py`.
- Dedupe engine (email OR phone match).
- Preview UX: "3421 customers · 87 will merge into existing · 3334 new".
- No commit — preview only.
- Est. LOC: **~600**.

### 5.3 Phase 55-c — Job + Recurring Schedule import (paper)

- Requires customer + property FK resolution — depends on 55-b being at least previewable.
- Enum mapping table for status field.
- RRULE generator from Homeworks frequency string.
- Est. LOC: **~500**.

### 5.4 Phase 55-d — Invoice + Payment + Quote import (paper)

- Line-item mapper with defensive snapshot handling (never rewrite `wholesale_price_snapshot`).
- Stripe charge ID passthrough.
- Invoice total sanity check.
- Est. LOC: **~700**.

### 5.5 Phase 55-e — Photo + Note attachment import (paper)

- Object-storage integration (may reuse existing integration if there is one, else needs the `integration_playbook_expert_v2` route).
- Streamed download from Homeworks CDN → re-upload to our storage → rewrite URLs.
- Skip activity log.
- Est. LOC: **~550**.

### 5.6 Phase 55-f — Commit + dry-run + rollback (REAL)

- Toggle the paper switch off.
- Preview screen → Commit button → progress modal → completion summary.
- Rollback flow: per-batch delete of all inserted rows (`batch_id` foreign-key on every inserted doc).
- Audit-log entries per batch.
- Est. LOC: **~450**.

**Total est. LOC across all 6 phases: ~3150**.

---

## 6. UX flow

### 6.1 Admin page

- Route: `/settings/import/homeworks`.
- Role gate: **admin + super_admin** only. Not manager — one-shot destructive-ish operation, higher trust bar.
- Sidebar entry: Reports group or a new "Data Migration" subsection. TBD in 55-a.

### 6.2 Credentials collection (only if Option C fallback triggers)

- Not needed in the CSV-primary path. If we degrade to Option C for photos or a missing entity: reuse the exact `supplier_credentials` pattern — Fernet-encrypted `homeworks_credentials` collection, `SUPPLIER_ENCRYPTION_KEY` reused.

### 6.3 Dry-run preview

- Post-parse screen shows counts per entity + collision summary.
- Example: "3421 customers · 87 matched to existing (will merge) · 3334 new · 12 warnings (email format invalid — will skip)."
- **Commit button disabled** until user reviews the warnings list.

### 6.4 Progress reporting for 10k+ records

- WebSocket **rejected** — over-engineered for a one-shot flow. Poll-based instead.
- Approach: `GET /api/imports/homeworks/batches/{id}` returns `{status, entity_progress: {customers: {done: 3421, total: 3421}, jobs: {done: 4200, total: 8500}, ...}}`.
- Frontend polls every 2 seconds while `status == "committing"`.
- **Chunking**: 500 records per insert batch to avoid Mongo request size limits + give the progress bar smooth ticks.

### 6.5 Failure handling

- **Locked policy: transactional-per-entity + resume-from-last-good-entity.**
- If customer import completes cleanly but job import errors on record 4201/8500: commit customers, halt jobs, mark batch `partial_failure`, expose Resume button that re-processes only records 4201+.
- Full rollback is available via the batch's `Rollback` button (deletes every doc with `import_batch_id == this_batch_id`).
- No mid-entity resume (record 4201 of jobs must retry all 8500 job records from that batch). Simpler correctness > partial-write cleverness.

---

## 7. Non-goals (locked per user's brief)

- No ongoing sync — one-shot only. Batch mechanics are single-use.
- No MFA / SSO handling — email+password only.
- No paid captcha solver or residential proxies. If Option C hits Turnstile, reuse Phase 54h-b bookmarklet handoff.
- Do not touch phase34 shim / Backlog #3 / Phase 54h / Phase 56.
- No dependencies on external services beyond what already exists.

---

## 8. Rollback plan per phase

Every inserted doc across 55-b through 55-f carries an `import_batch_id` field. Rollback = single-command purge:

```
db.customers.delete_many({"import_batch_id": <batch>})
db.customer_locations.delete_many({"import_batch_id": <batch>})
... (repeat for every collection touched)
```

- **Phase 55-a rollback**: drop the staging collection `homeworks_import_batches`. Zero user-facing effect.
- **Phase 55-b/c/d/e rollback**: paper — no user-facing effect, just deletion of test-run data + code revert.
- **Phase 55-f rollback**:
  - Code-level: revert commit endpoint. Preview + parse still work.
  - Data-level: per-batch `import_batch_id` purge (above). Idempotent.

---

## 9. Open questions for user review

1. **Log into Copilot CRM once and confirm/deny the CSV export surface.** Screenshot each entity's Export button (or "does not exist"). This decides B-primary vs C-fallback scope split at the entity level.
2. **Do you have Stripe on the Copilot CRM side?** If yes, we can pass through `stripe_charge_id` on payments — no re-charge needed and reconciliation is one-liner. If no, payments are historical-record-only imports.
3. **Recurring schedules — does Copilot CRM expose the source's frequency as human-readable ("every 2 weeks") or as RRULE? We'll need to build the mapper accordingly.
4. **Photos: copy-into-our-object-storage (heavy, correct) vs reference-only (light, brittle)?** Default proposed: copy-into. Storage cost estimate needed if you have 10k+ jobs each with 3-5 photos → ~50 GB.
5. **Technician mapping**: Homeworks side has "assigned_tech" strings. Our side has `users` with roles. Fuzzy-name match with a warning-on-ambiguity prompt, or manual mapping page pre-commit?
6. **Timeline pressure**: is this a paid pilot for a specific customer with a hard start date, or an internal migration? Determines whether we ship 55-a through 55-f sequentially (~2-3 weeks) or parallelize with more risk.
7. **Rollback expectation**: is the user comfortable with per-batch soft-delete of imported records, or do they want the entire batch to appear as a "namespace" that can be viewed/hidden without deleting?

---

## 10. Recommended next step

Before dispatching Phase 55-a:

- **User action 1**: Log into `secure.copilotcrm.com`, walk through Customers / Jobs / Invoices export options. Screenshot findings.
- **User action 2**: Answer open questions 1-7 above (rapid — most are one-liner decisions).
- **Then**: dispatch Phase 55-a with the concrete B-vs-C entity split locked in.

If the user just wants to proceed without confirming exports (accept the B-primary bet and degrade later): dispatch 55-a as scaffolding-only, which is safe regardless of the B-vs-C outcome because it's a paper connection and admin UI shell only.

---

**End of design doc.** Awaiting user review + approval or steer.
