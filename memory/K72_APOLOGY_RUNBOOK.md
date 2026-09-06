# K72.b · Apology Dispatch Runbook

**Owner:** platform ops (user runs on prod today after redeploy)
**Script:** `/app/scripts/k72_apology_send.py`
**Companion memo:** `/app/memory/PHASE_K72_EMERGENCY_NO_FILTER_EMAIL_DIAG.md`
**Blast radius:** 113 real customers on tenant `aquaterra` (`Pool & Landscaping of Vistancia`).
**Approved by user:** apology text, send method (CRM via `cs@plofv.com`), `[SUPPORT_PHONE] = 602-887-4400`.

---

## 0 · TL;DR (paste-and-run)

```bash
# On the PROD pod, in the folder that owns backend/.env:
cd /app

# 1. Dry-run first \u2014 sanity check every recipient + first-name merge.
python /app/scripts/k72_apology_send.py --dry-run

# 2. If the dry-run output looks right, ship it live.
python /app/scripts/k72_apology_send.py --commit
```

Idempotent. Rerun is safe \u2014 already-sent recipients are skipped by the audit-row check.

---

## 1 · Pre-flight (do this BEFORE `--commit`)

The script's own preflight will refuse the run if any of the below fail. This is a human checklist to make the refusal outcome predictable.

- [ ] **K72.fix + K72.a + K72.1 are on prod.** Confirmed by:
  - `GET /api/mass-messaging/send` (unauthed) returns 401.
  - As admin, a `POST /api/mass-messaging/send` `{audience: "all_active_customers"}` on prod succeeds (guarded by the confirm modal + `is_real=True` tenant check), while the same call on preview returns HTTP 403 `K72_REAL_TENANT_NON_PROD_BLOCKED`.
  - `test_bug_g_mass_messaging_filters.py` returns `1 skipped, 0 collected`.
- [ ] **`APP_ENV=production` in prod pod's `/app/backend/.env`.** `grep '^APP_ENV' /app/backend/.env`
- [ ] **`FEATURE_CUSTOMER_EMAIL_KILL_SWITCH=off`** in prod pod's `/app/backend/.env`. **This one is critical.** If the switch is ON the Resend adapter will convert every apology send to a dry-run envelope and the audit rows will land as `status="suppressed"` \u2014 the customers will hear nothing. Flip the kill switch back ON **after** the apology dispatch finishes, if you still want it on.
- [ ] **`RESEND_API_KEY` set** in prod pod's `/app/backend/.env`. Without it the adapter runs in mocked mode (`provider_status="mocked"`) \u2014 no send happens.
- [ ] **Prod pod has the K72 memo checked in** at `/app/memory/PHASE_K72_EMERGENCY_NO_FILTER_EMAIL_DIAG.md`. The script parses the recipient table from section 3 of that file \u2014 no memo, no roster.
- [ ] **Prod Mongo has the aquaterra tenant** with `id=affdfbfa-88b9-4baa-ae45-2ef78531b6e4`. The script warns (does not block) on id drift, but you want the id match for the audit trail to reconcile.

---

## 2 · Run the dry-run

```bash
python /app/scripts/k72_apology_send.py --dry-run
```

Expected output shape:

```
PREFLIGHT
=========
  - (all checks passed)

Parsed 118 roster rows \u2014 113 real recipients after filtering.
Tenant: slug=aquaterra id=affdfbfa-88b9-4baa-ae45-2ef78531b6e4
Mode:   DRY-RUN (no writes)
  [  1/113] DRY_RUN   rblake@outlook.com                       first='Robert' rid=
  [  2/113] DRY_RUN   mgomez@yahoo.com                         first='Maria'  rid=
  ...
SUMMARY
=======
  attempted        : 113
  sent             : 0
  failed           : 0
  dry_run          : 113
  mocked (no key)  : 0
  skipped duplicate: 0
  skipped no-retry : 0
```

**What to eyeball on the dry-run:**
- Total attempted = **113**. If it's less (`101`, `108`, etc.) the filter or the memo has drifted \u2014 stop and investigate before committing.
- First-name resolution: at least ~90% of rows should show a real first name (`'Robert'`, `'Maria'`, ...). A pile of `first='there'` fallbacks means the `customers` collection isn't finding matches by email \u2014 check for a data drift between preview and prod.
- Email addresses match section 3 of the K72 memo.

---

## 3 · Ship it (`--commit`)

```bash
python /app/scripts/k72_apology_send.py --commit
```

- Rate-limited to 5 sends / second (200 ms sleep between). Expected wall time: **~25 seconds** for 113 recipients (matches the original 24-second burst window, which was the point).
- Each recipient's row is written to `db.k72_apology_dispatch` before the next one is attempted \u2014 a mid-run crash leaves a partial trail, not a phantom send.
- Reruns are safe: recipients with an existing `status="sent"` audit row are skipped.

**Exit codes:**
- `0` \u2014 all sends succeeded (or dry-run completed).
- `1` \u2014 at least one send failed. See the FAILURES block in the summary; rerun with `--commit --retry-failed` to attempt only those.
- `2` \u2014 preflight blocked. Fix the reported issue and rerun.
- `3` \u2014 roster empty or memo missing.

---

## 4 · Post-flight verification

1. **Resend dashboard** \u2014 https://resend.com/emails filtered by:
   - From: `cs@plofv.com`
   - Subject: `A quick apology from Pool & Landscaping of Vistancia`
   - Expected count: **113 delivered**, 0 failed / bounced.
   Any bounce > 0? Grab the address list from Resend and confirm the corresponding `k72_apology_dispatch` row has `status="failed"` with the bounce reason.

2. **Sample 3 customer inboxes** \u2014 use the same three named customers the tenant already heard back from:
   - Michelle Moore (`michellelmoore@hotmail.com`)
   - Scott Muir (`muir.scott62@gmail.com`)
   - Alan Chesebrough (`alanchesebrough@gmail.com`)
   Confirm the apology landed adjacent to the original `no-filter` thread (same From address, so Gmail / Outlook should group them).

3. **Mongo audit row spot-check** \u2014
   ```javascript
   db.k72_apology_dispatch.aggregate([
     { $match: { dispatch_id: "k72.b.apology.2026-02" } },
     { $group: { _id: "$status", n: { $sum: 1 } } },
   ])
   // Expect: [{ _id: "sent", n: 113 }]
   ```

4. **Reply monitoring** \u2014 the apology invites replies to `cs@plofv.com` and the `602-887-4400` line. Watch both for the next 48 hours; expect a small volume of "thanks for letting me know" replies and possibly 1\u20132 "actually, while I have you, can you look at X" reroutes into normal service tickets.

---

## 5 · Rollback

**None available.** Email is one-way \u2014 once Resend returns a message id the customer's mail server has the message. If the script fires wrong (wrong subject, wrong body, wrong list), that is a **fresh incident** and requires its own follow-up. That's why the dry-run in section 2 is non-negotiable.

If mid-run you realise something is wrong:

```bash
# Ctrl-C the running script. Any recipient already emailed has an
# audit row \u2014 the rerun will skip them by default.
# Diff the intended vs actual recipients:
mongo "$MONGO_URL" --eval '
  db.k72_apology_dispatch.find(
    { dispatch_id: "k72.b.apology.2026-02" },
    { email: 1, status: 1, _id: 0 }
  ).toArray()
'
```

---

## 6 · Cost estimate

- Resend transactional pricing (per Resend's public pricing, verify current tier in the account): a 113-email one-shot is effectively free \u2014 well within any paid plan's monthly quota and comfortably inside the free-tier day limit.
- No SMS component. No template rendering fees.
- The audit rows in Mongo are ~500 bytes each \u2014 negligible.

---

## 7 · Sequencing with the kill switch

The user's plan is:
1. Redeploy prod today with K72.fix + K72.a + K72.1 baked in.
2. Run `--dry-run` \u2192 review \u2192 `--commit`.
3. Flip `FEATURE_CUSTOMER_EMAIL_KILL_SWITCH=on` **after** step 2 completes.

**If steps 2 and 3 are reversed** the apology never leaves the pod. The script's preflight will refuse `--commit` when the switch is ON \u2014 that's a load-bearing guard, not a nag.

---

## 8 · Files touched

- `/app/scripts/k72_apology_send.py` \u2014 the dispatcher.
- `/app/memory/K72_APOLOGY_RUNBOOK.md` \u2014 this document.
- `db.k72_apology_dispatch` \u2014 audit collection (created lazily by the first `--commit` write).

**No production code changes.** This is a one-shot admin tool that reuses the existing Resend adapter and its K72 kill-switch / K30 allow-off-allowlist / K72.a `audience` plumbing exactly as-is.
