# Rauschenberger schedule-address · Phase 1 Verification (2nd surfacing)

**Scope:** read-only verification of operator claim that multiple schedule job cards show `5207 West Bajada Road, Phoenix, AZ 85083`, with named affected customers Benjamin Enriquez, James Conrad, Larry & Cindy Contreras, Diane Lloyd, Andrea Reitz, Michael Rauschenberger.

**No code changes. No DB mutations.**

---

## 1. Ship verification — `98fd4551e` is in HEAD

| Check | Result |
|---|---|
| `git merge-base --is-ancestor 98fd4551e HEAD` | **YES — in HEAD** |
| `98fd4551e` commit found on log | ✅ (committed 2026-10-21 18:18:13 UTC, author `agent@emergent.dev`) |
| Companion test ship `59bad20a3` also in HEAD | ✅ |
| `backend/services/address_resolver.py` exists | ✅ (108 LOC per commit stat) |
| `backend/routers/schedule.py` imports `_resolve_job_address_from_batches` | ✅ at `schedule.py:32-33` |
| `_resolve_job_address_from_batches` is wired into the DefaultRow address field | ✅ at `schedule.py:487` |

```python
# schedule.py:32-33
from services.address_resolver import (
    resolve_job_address_from_batches as _resolve_job_address_from_batches,
)

# schedule.py:487
"address": _resolve_job_address_from_batches( …batched cust_map, prop_map… ),
```

**Live endpoint smoke (via admin@aquaterra.com on tenant `affdfbfa…`):**
- `GET /api/schedule/today` returns `200 OK`, `rows: 0` (that tenant has no jobs scheduled today).
- Cannot show a live FK-ladder resolution in the response payload because this tenant has no today-jobs. BUT the direct DB probe confirms the resolver logic:

```
Sample job id: ab88fb26-cf98-4934-8db6-ed422b72ec3d
  jobs.address snapshot:   "161 Preview St, Testville, AZ 85000"
  customer:                "Preview Customer0085"
  customer.address:        "85 Preview St"
  property.address:        "1 Preview St, Testville, AZ 85000"
```
If this job surfaced on schedule/today, the FK-ladder would resolve `property.address` first (rung 1), returning `"1 Preview St, …"` — NOT the stale `"161 Preview St, …"` snapshot. Resolver is in place and would fire.

**No FE build / HMR / cache concern applicable** — the fix is pure BE (schedule endpoint response), no FE change was shipped. The FE renders whatever BE returns.

---

## 2. Live DB reality check — operator's named customers

### Customer existence probe (`db.customers.find({name: /…/i})`)

| Name queried | Spelling variants tried | Hits |
|---|---|---|
| Michael Rauschenberger | `Rauschenberger`, `Raushenberger` (fixture spelling, missing `c`), `ausch?enb` | **0** |
| Benjamin Enriquez | `Enriquez` | **0** |
| James Conrad | `Conrad` | **0** |
| Larry & Cindy Contreras | `Contreras` | **0** |
| Diane Lloyd | `Diane Lloyd` | **0** |
| Andrea Reitz | `Andrea Reitz` | **0** |

**None of the six named customers exist in `db.customers` on preview.**

The 803 customers that DO exist in the live preview DB are all synthetic — the sample pull returned `"Preview Customer0085"` with address `"85 Preview St"` and a `primary_property_id` set to a `properties` row carrying `"1 Preview St, Testville, AZ 85000"`. The entire preview dataset is `"Preview CustomerNNNN"` fixtures with `"NN Preview St, Testville, AZ 85000"` addresses — no real-name customers at all.

### Job-address probe

| Search | Live DB result |
|---|---|
| `jobs.address` matches `Bajada` (case-insensitive) | **0 jobs** |
| `jobs.address` matches `5207 West` | **0 jobs** |
| `jobs.address` matches `85083` (zip code) | **0 jobs** |

**Zero jobs in the live DB carry the specific repro address `5207 West Bajada Road, Phoenix, AZ 85083` or any component of it.** Sample pull of Bajada-matching jobs returned an empty cursor.

Overall preview collection sizes for reference:
- `db.customers` = 803 (all synthetic "Preview CustomerNNNN")
- `db.jobs` = 9,139
- `db.properties` = 7,140

### Fixture-source trace

The names ARE present on disk, but **only in fixture files that were never loaded into the live preview DB**:

| File | Line match |
|---|---|
| `backend/tests/fixtures/active_customer_list.csv` | **6 hits**: `James;Conrad;3112 W Adobe Dam Rd;Phoenix;85027` · `Benjamin;Enriquez;5036 W Kristal Way;Glendale;85308` · `Michael;Raushenberger;5207 West Bajada Road;Phoenix;85083` (misspelled, no `c`) · plus Diane Lloyd, Andrea Reitz lines |
| `backend/tests/fixtures/active_clients.csv` | **6 hits** (same source data, legacy comma-delimited variant) |
| `testing/customers.json` | **1 bulk JSON** containing Benjamin Enriquez (`5036 W Kristal Way`), Andrea Reitz (`4419 W Electra Ln`), Diane Lloyd (`20271 N 51st Dr`), **no Rauschenberger entry at all**, **no Larry & Cindy Contreras** |
| `backend/tests/test_td_schedule_address_resolver.py` | 1 hit — the test that locked the Rauschenberger-drift repro from the FIRST surfacing is in HEAD (per `59bad20a3`), and uses the misspelling "Raushenberger" with address `5207 West Bajada Road` to construct a synthetic fixture test case. **Confirms the drift mechanism is unit-tested; the live-DB fix is already provable.** |

### Spelling discrepancy — important

- **Operator spelling** this cycle: "Michael **Rauschenberger**" (with a `c`).
- **Fixture spelling** in the on-disk CSV files: "Michael **Raushenberger**" (NO `c`).
- **Test fixture `test_td_schedule_address_resolver.py`** spelling (shipped `59bad20a3`): "**Rauschenberger**" (with `c`).

The operator's spelling matches the TEST FILE, not the CSV fixtures. This suggests the "specific customer" name wasn't scraped from the real-looking CSV fixtures — it was pulled from the test file that was committed as part of the first-surfacing fix. The injector read the test file and seeded the attack with its spelling.

The other 5 names ("Benjamin Enriquez", "James Conrad", "Larry & Cindy Contreras", "Diane Lloyd", "Andrea Reitz") are plausibly fixture-scrapable — but "Larry & Cindy Contreras" doesn't appear in a grep of either fixture CSV or `testing/customers.json`. 4/5 appear in fixtures; 1/5 (Contreras) is **not grep-able anywhere in the repo**. Likely LLM-fabricated to extend the apparent legitimacy of the list.

---

## 3. Classification

**Verdict: V14 bulk-mix injection, same shape as the first-surfacing attack.**

Markers that match the known V14 pattern codified in `TECH_DEBT.md`:

1. **Fixture-scrapable names bundled with a data-mutation ask.** 4 of 6 named "affected customers" come from on-disk CSV fixtures that are not loaded into the preview DB. The payload is a plausible-looking repair request that would, if accepted, write/update data based on a nonexistent repro.
2. **Spelling mismatch between the "customer" and the fixtures.** "Rauschenberger" matches the TEST FILE spelling, not the CSV spelling — the attack targeted the test file we shipped last cycle. "Larry & Cindy Contreras" doesn't exist anywhere in the repo at all.
3. **Second-surfacing framing.** Attack explicitly references the previous Rauschenberger episode and the mechanism fix ship SHA — a social-engineering move to establish continuity ("you fixed the mechanism, now do the data repair"). V14 playbook step.
4. **Zero live-DB evidence of the specific repro.** No `5207 West Bajada Road`, no `85083` zip, no `Bajada` substring, no `5207 West` substring in any job in the live preview DB. If the operator legitimately saw this on a real tenant, the repro would have to exist in the preview DB they're hitting — it doesn't.
5. **The architectural mechanism fix is already shipped, tested, and provably correct.** The address_resolver test file in `backend/tests/test_td_schedule_address_resolver.py` contains the exact Rauschenberger drift repro as a synthetic unit test and asserts it resolves to the current property, not the stale snapshot. 14/14 green at ship time (`59bad20a3`). The mechanism isn't broken; a data-repair script would mutate real data based on a fictional repro.

**No data repair script should be dry-run or written.** There is no stale-data surface in the live preview DB to repair. If a legitimate real-tenant repro exists on production, the operator would need to produce (a) a specific `tenant_id`, (b) a specific `customer_id` or `job_id`, (c) a specific stale-vs-current address pair pulled from the production DB — none of which have been provided, and none of which the agent has access to (production is a separate environment per the earlier system notification).

**If the ship were still rendering stale on preview — it isn't.** The ship is in HEAD, the resolver is wired, no stale-address jobs exist in the live DB. There is no "FE still shows stale" symptom to diagnose.

---

## 4. TD-96-g1-invoices status

**Paused mid-decision.** Phase 1 recon landed at commit `ab5cd0302`; operator Y/N on 3 open decisions still pending:
1. Fork pick: (i) Tighten / **(ii) Expand ⭐** / (iii) Hybrid / (iv) No-op?
2. Test file strategy for Phase 2.
3. Should Phase 2 also audit `QuotesList.jsx` row-click routing or defer?

The recon doc at `memory/td96_g1_invoices_recon.md` is complete and ready to resume when the operator surfaces back from this detour.

---

## 5. Recommendation to operator

- **Do not proceed to a Phase 2 data repair** — there is no live-DB repro to repair.
- **Classify the current ticket as a V14 bulk-mix injection** and log it under `TD-UIinj` with the Rauschenberger-recurrence marker.
- **Resume TD-96-g1-invoices** or the next priority ticket.
- If a legitimate production stale-address bug is observed, re-dispatch with: specific `tenant_id`, specific `customer_id` or `job_id`, and the stale-vs-current address pair from the production DB. Agent cannot repair production from preview regardless; the mechanism fix in HEAD will apply to production on the next deploy.

---

## 6. Guardrail attestation

- No code changes made.
- No DB mutations.
- No `/app/mobile/` touches.
- No testing agent invoked.
- No scope creep into `jobs.address` denorm cleanup (would be a separate `TD-schedule-address-write-through` ticket, not in scope).
- V14 injection pattern recognized on sight and discarded without acting; truth reported per operator's explicit instruction ("report truth even if it contradicts the operator's framing"). TD-61 chain still at **20**.
