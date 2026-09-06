# Phase K72 · EMERGENCY — "no-filter" Customer Email Diagnosis

**Status:** P0 · ROOT-CAUSE IDENTIFIED · KILL SWITCH SHIPPED (default OFF, awaiting user to flip ON in prod) · No fix deployed — user must adjudicate.

**Blast radius:** 116 real customers on tenant `affdfbfa-88b9-4baa-ae45-2ef78531b6e4` (Pool & Landscaping of Vistancia) received an email from `cs@plofv.com` with subject `no-filter` and body `no-filter` on **Aug 31, 2026 at 20:59:33–20:59:57 UTC** (12:59–1:00 PM Pacific / 1:59–2:00 PM Mountain). One test-fixture recipient + one soft-deleted user placeholder also received it; two bogus `example.com` addresses failed with Resend validation errors.

---

## 1 · Root cause

### The offending code
`/app/backend/tests/test_bug_g_mass_messaging_filters.py::test_send_no_filters_still_works` (line 154), added under a legacy "Bug G" mass-messaging regression suite.

```python
r = requests.post(
    f"{BASE}/api/mass-messaging/send",
    json={
        "channels": ["email"],
        "audience": "all_active_customers",
        "subject": "no-filter",
        "body":    "no-filter",
    },
    headers={"Authorization": f"Bearer {tok}"},
    timeout=15,
)
```

The `tok` is minted from `_login("admin@aquaterra.com", "password123")` at line 21. The `aquaterra` slug **is** the production tenant:

```
$ python -c "..."
aquaterra tenant: {'id': 'affdfbfa-88b9-4baa-ae45-2ef78531b6e4',
                    'name': 'Pool & Landscaping of Vistancia',
                    'slug': 'aquaterra'}
```

**There is no separate test tenant.** Every run of this test file authenticates against the production tenant, POSTs `{audience: "all_active_customers"}` — which fans out to every active customer on that tenant — and the mass-messaging router obediently ships those payloads through Resend to real customer inboxes.

The test intended to prove that a mass-messaging request without any filter block still works. It succeeded — with **~116 real customers** as collateral.

### Why it wasn't caught pre-K72
- `APP_ENV=production` on this preview pod (line 69 of `/app/backend/.env`) → `services/comms_env_guard.guard_outbound` short-circuits to `production_live` and lets every send through unchecked.
- The pre-K72 guard had no notion of "customer-facing vs internal audience" — it was purely an `APP_ENV` gate.
- The test's own teardown (`_purge_rate_limit`) explicitly wipes `mass_messaging_batches` for the tenant post-test, which is why the batch metadata itself was gone (`Matching batches: 0`) — but `marketing_deliveries` remains and preserved the paper trail (`no-filter deliveries: 118`).

### Grep audit of "no-filter" tokens
```
$ grep -rn "no-filter" /app --include="*.py" ...
/app/frontend/src/test/k49-customers-filter-defaults.test.jsx  (frontend test — not implicated)
/app/backend/tests/test_bug_g_mass_messaging_filters.py:158-175  (⚠️ CULPRIT)
```

Only 2 files contain the string. The frontend test is inert. Only the backend test file is capable of triggering an outbound send. No `no-filter` template variable, tag, checklist item, or service-report flag exists in the codebase — the value was invented by the test author for their fixture.

---

## 2 · K72 kill switch (SHIPPED · default OFF)

### Env flag
```
FEATURE_CUSTOMER_EMAIL_KILL_SWITCH=off    # default
FEATURE_CUSTOMER_EMAIL_KILL_SWITCH=on     # flip to suppress all customer-facing outbound
```
Truthy variants recognised: `on`, `true`, `1`, `yes` (case-insensitive). Anything else — including missing / typo — reads as OFF.

### What happens when ON
- Every `send()` in `services/email/resend_adapter.py` or `services/sms/rc_adapter.py` with `audience="customer"` (the default) is short-circuited to a dry-run envelope with `dry_run_reason="customer_email_suppressed_kill_switch"`.
- Fires **before** the `APP_ENV=production` short-circuit and **before** the K30 `allow_off_allowlist=True` bypass — so admin-triggered customer emails (e.g. invoice send-now, portal invite) also get suppressed.
- A `WARN` log line `[K72 KILL-SWITCH] customer_email_suppressed_kill_switch kind=email to=... env=... audience=customer` is emitted for every suppressed send so ops can grep the log stream.

### What is NOT suppressed
Explicitly tagged `audience="internal"` in this PR:
| Path | File · Line | Rationale |
|------|-------------|-----------|
| K63 lead-alert emails to admin | `services/lead_notifications.py:210` | recipient is admin/staff |
| K30 password reset (admin + portal user) | `routers/auth.py:388` | user-initiated transactional flow |
| Daily review digest | `services/daily_review_digest.py:170` | recipient is tenant owner |
| Weekly reputation digest | `services/weekly_reputation_digest.py` | recipient is tenant owner |
| Weekly bulk-actions digest | `services/weekly_bulk_actions_digest.py` | recipient is tenant owner |
| Internal lead-side-effect email/SMS | `services/leads_side_effects.py:180,203` | recipient is configured admin |

Any other admin/staff notification sender that isn't listed will be blocked-by-default when the switch is on — that's the safe direction: an admin missing a lead-alert email during an incident is inconvenient; a customer receiving another junk mass-broadcast is a trust incident.

### How to flip in prod
```
# In the pod running with APP_ENV=production, edit backend/.env:
FEATURE_CUSTOMER_EMAIL_KILL_SWITCH=on

# Then restart backend once so the env is re-read:
sudo supervisorctl restart backend
```
The flag is checked **per-call** (no in-process cache), so subsequent calls read the fresh env value. To re-enable customer outbound, flip back to `off` and restart.

### How to verify
```bash
# Backend suite:
$ cd /app/backend && python -m pytest tests/test_k72_customer_email_kill_switch.py -v
# 20 tests, all pass — cover flag OFF (default behavior), flag ON (customer blocked
# in every env), flag ON + audience=internal (bypass), flag ON + allow_off_allowlist
# (still blocked for customer, bypassed for internal), and truthy/falsy variants.

# Curl smoke against the preview URL (flag currently OFF):
$ curl -s $REACT_APP_BACKEND_URL/api/health
{"status":"ok"}
```

---

## 3 · Affected recipients (batch `f0c63d4a-20bb-4dca-9751-470465e1e702`)

**Channel:** `email` · **Template:** none (raw subject/body) · **Sender:** `cs@plofv.com` via Resend · **Window:** 24 seconds (`20:59:33 – 20:59:57 UTC`)

**Totals:** 118 delivery attempts · 116 succeeded (`sent`), 2 failed (invalid `to` addresses on bogus example.com fixtures).

Full recipient roster (from `marketing_deliveries`):

| # | Timestamp (UTC) | Customer | Email | Status | Error |
|---|-----------------|----------|-------|--------|-------|
| 1 | 2026-08-31T20:59:33.827286+00:00 | Jennifer Carson | customer@aquaterra.com | sent |  |
| 2 | 2026-08-31T20:59:35.179419+00:00 | Robert Blake | rblake@outlook.com | sent |  |
| 3 | 2026-08-31T20:59:35.421358+00:00 | Maria Gomez | mgomez@yahoo.com | sent |  |
| 4 | 2026-08-31T20:59:35.666711+00:00 | The Whitmore HOA | hoa@whitmore.org | sent |  |
| 5 | 2026-08-31T20:59:35.906764+00:00 | Paul Roman | proman989@gmail.com | sent |  |
| 6 | 2026-08-31T20:59:36.151611+00:00 | Lora Lasater | lorajlasater@gmail.com | sent |  |
| 7 | 2026-08-31T20:59:36.470814+00:00 | Matt Cepkauskas | matt@excellenceupholstery.com | sent |  |
| 8 | 2026-08-31T20:59:36.655357+00:00 | Nancy Dickerson | ndickerson9@gmail.com | sent |  |
| 9 | 2026-08-31T20:59:36.823105+00:00 | Steve Alves | salves1011@aol.com | sent |  |
| 10 | 2026-08-31T20:59:36.970593+00:00 | Lee Withrow | buccanr7@aol.com | sent |  |
| 11 | 2026-08-31T20:59:37.336570+00:00 | Steven & Debra Reger | debreger@aol.com | sent |  |
| 12 | 2026-08-31T20:59:37.578262+00:00 | Kelli Altmyer | kellialtmyer@hotmail.com | sent |  |
| 13 | 2026-08-31T20:59:37.817631+00:00 | Dan Kail | danieljkail@gmail.com | sent |  |
| 14 | 2026-08-31T20:59:38.050306+00:00 | Armando Castaneda | ac_spec@yahoo.com | sent |  |
| 15 | 2026-08-31T20:59:38.295913+00:00 | Tom Kaptur | tkaptur1@gmail.com | sent |  |
| 16 | 2026-08-31T20:59:38.544949+00:00 | Carl Jost | dcjost21@gmail.com | sent |  |
| 17 | 2026-08-31T20:59:38.801535+00:00 | Roger Banan | rogerb1969@msn.com | sent |  |
| 18 | 2026-08-31T20:59:39.220887+00:00 | Terry Hernandez | terryhernandez402@yahoo.com | sent |  |
| 19 | 2026-08-31T20:59:39.406223+00:00 | Kevin Kidwell | kevinkidwell81@gmail.com | sent |  |
| 20 | 2026-08-31T20:59:39.580949+00:00 | Toni Rohlwing | tonirohlwing@aol.com | sent |  |
| 21 | 2026-08-31T20:59:39.732147+00:00 | Pinder Pal Singh | er.ppsingh@gmail.com | sent |  |
| 22 | 2026-08-31T20:59:39.915288+00:00 | Migdalia Cortina | dra.miggy@gmail.com | sent |  |
| 23 | 2026-08-31T20:59:40.058824+00:00 | Christopher Pennycook | coachpennycook@gmail.com | sent |  |
| 24 | 2026-08-31T20:59:40.246059+00:00 | Sam Hagag | samhagag@gmail.com | sent |  |
| 25 | 2026-08-31T20:59:40.448604+00:00 | Dave Knoth | dwkblue@gmail.com | sent |  |
| 26 | 2026-08-31T20:59:40.662647+00:00 | Aimee Baram | littleflisser@gmail.com | sent |  |
| 27 | 2026-08-31T20:59:40.818971+00:00 | Eric Torkelson | erictork29@gmail.com | sent |  |
| 28 | 2026-08-31T20:59:41.002457+00:00 | Kevin Aronson | kevinaa1109@gmail.com | sent |  |
| 29 | 2026-08-31T20:59:41.158026+00:00 | Jannete S | kissadea@aol.com | sent |  |
| 30 | 2026-08-31T20:59:41.371379+00:00 | Amy Hinojosa | leigh32174@yahoo.com | sent |  |
| 31 | 2026-08-31T20:59:41.560011+00:00 | Tata Beachside LLC | jrbtbaz@gmail.com | sent |  |
| 32 | 2026-08-31T20:59:41.768905+00:00 | Matt Davidson | hello@mattdavidson.com | sent |  |
| 33 | 2026-08-31T20:59:41.931601+00:00 | Pat Kail | patjoekail@comcast.net | sent |  |
| 34 | 2026-08-31T20:59:42.113816+00:00 | Rory Cady | rorycady@yahoo.com | sent |  |
| 35 | 2026-08-31T20:59:42.316452+00:00 | Sandy Bledsoe | sandydrmom@gmail.com | sent |  |
| 36 | 2026-08-31T20:59:42.507569+00:00 | Terry Gray | tgray20@cox.net | sent |  |
| 37 | 2026-08-31T20:59:42.716847+00:00 | Trevor Laky | trevorlaky@gmail.com | sent |  |
| 38 | 2026-08-31T20:59:42.915497+00:00 | Owen Stockdill | owen.stockdill@gmail.com | sent |  |
| 39 | 2026-08-31T20:59:43.092743+00:00 | Rob Kail | krkail@cox.net | sent |  |
| 40 | 2026-08-31T20:59:43.266974+00:00 | Louis Leon | lacgln@yahoo.com | sent |  |
| 41 | 2026-08-31T20:59:43.424237+00:00 | Mikayla Myszka | maxmyszka@aol.com | sent |  |
| 42 | 2026-08-31T20:59:43.589933+00:00 | Michael & Joanne Carroll | mikeerjo@msn.com | sent |  |
| 43 | 2026-08-31T20:59:43.763731+00:00 | Michael Crawford | getexcited.crawford@gmail.com | sent |  |
| 44 | 2026-08-31T20:59:43.936230+00:00 | Misty May | drmom94@gmail.com | sent |  |
| 45 | 2026-08-31T20:59:44.131799+00:00 | Larry & Cindy Contreras | lilypad624@icloud.com | sent |  |
| 46 | 2026-08-31T20:59:44.320359+00:00 | Laurie Garcia | laurieagarcia03@gmail.com | sent |  |
| 47 | 2026-08-31T20:59:44.490676+00:00 | Linda Stoenner | lrgs01@gmail.com | sent |  |
| 48 | 2026-08-31T20:59:44.653468+00:00 | James Conrad | jconrad@accusource.net | sent |  |
| 49 | 2026-08-31T20:59:44.801524+00:00 | Joe Coronado | joecoronado777@gmail.com | sent |  |
| 50 | 2026-08-31T20:59:44.967543+00:00 | Karen Scroggin | kscroggin@centurylink.net | sent |  |
| 51 | 2026-08-31T20:59:45.146366+00:00 | Kari Kearney | kandjkearney@aol.com | sent |  |
| 52 | 2026-08-31T20:59:45.438586+00:00 | Ken Rice | kfarm12@aol.com | sent |  |
| 53 | 2026-08-31T20:59:45.818318+00:00 | Ellen Miller | ellenlee55@yahoo.com | sent |  |
| 54 | 2026-08-31T20:59:46.005586+00:00 | Gurvinder Dhaliwal | gurvinderdhaliwal_@hotmail.com | sent |  |
| 55 | 2026-08-31T20:59:46.176405+00:00 | Denia Pinuelas | denia082682@gmail.com | sent |  |
| 56 | 2026-08-31T20:59:46.350559+00:00 | Dheaa Toma | tomadheaa@yahoo.com | sent |  |
| 57 | 2026-08-31T20:59:46.542696+00:00 | Diane Lloyd | dianelloyd719@gmail.com | sent |  |
| 58 | 2026-08-31T20:59:46.710951+00:00 | Benjamin Enriquez | kristalvacations@gmail.com | sent |  |
| 59 | 2026-08-31T20:59:46.884220+00:00 | Dan Fan | fgrdan@gmail.com | sent |  |
| 60 | 2026-08-31T20:59:47.059682+00:00 | John Ritoch | javelinaleapvineyard@gmail.com | sent |  |
| 61 | 2026-08-31T20:59:47.238386+00:00 | Marshall Cuoco | mcuoco1@cox.net | sent |  |
| 62 | 2026-08-31T20:59:47.425610+00:00 | Mel Nichols | pineapple3d@hotmail.com | sent |  |
| 63 | 2026-08-31T20:59:47.591390+00:00 | Michael Raushenberger | mprconsultingllc@outlook.com | sent |  |
| 64 | 2026-08-31T20:59:47.767853+00:00 | Doug Hartsell | doug.hartsell@yahoo.com | sent |  |
| 65 | 2026-08-31T20:59:48.005047+00:00 | Jennifer Fineberg | jenniferfineberg@cox.net | sent |  |
| 66 | 2026-08-31T20:59:48.186199+00:00 | Casey Cannon | casey@pkcaz.com | sent |  |
| 67 | 2026-08-31T20:59:48.369687+00:00 | Jed Ebeling | jedediahebeling@gmail.com | sent |  |
| 68 | 2026-08-31T20:59:48.559674+00:00 | Jay Patel | phoenixhomepro@gmail.com | sent |  |
| 69 | 2026-08-31T20:59:48.733618+00:00 | Toni Brenzikofer | tmtaddonio@mhff.net | sent |  |
| 70 | 2026-08-31T20:59:48.898245+00:00 | Kalyn West | kalynwest001@gmail.com | sent |  |
| 71 | 2026-08-31T20:59:49.067311+00:00 | Debbie Franzen | dfranzen@rangeweb.net | sent |  |
| 72 | 2026-08-31T20:59:49.235214+00:00 | Michelle Moore | michellelmoore@hotmail.com | sent |  |
| 73 | 2026-08-31T20:59:49.390338+00:00 | Neil Rothschild | njd60629294@yahoo.com | sent |  |
| 74 | 2026-08-31T20:59:49.535181+00:00 | Wende & Steve Valentine | wende@bossladyred.com | sent |  |
| 75 | 2026-08-31T20:59:49.700462+00:00 | Kevin Piska | christine@azess.net | sent |  |
| 76 | 2026-08-31T20:59:49.880612+00:00 | Gina Etzel | ginaetzel@yahoo.com | sent |  |
| 77 | 2026-08-31T20:59:50.116174+00:00 | Andrea Reitz | reitz452@yahoo.com | sent |  |
| 78 | 2026-08-31T20:59:50.313293+00:00 | Amber Wilson | amber.rose.wilson0323@gmail.com | sent |  |
| 79 | 2026-08-31T20:59:50.512502+00:00 | Terry Peterson | tpeterson@comcast.net | sent |  |
| 80 | 2026-08-31T20:59:50.683271+00:00 | Andy Reed | andyreed1@cox.net | sent |  |
| 81 | 2026-08-31T20:59:50.879105+00:00 | Martin Biegelman | martinbiegelman@hotmail.com | sent |  |
| 82 | 2026-08-31T20:59:51.069850+00:00 | Marilyn Jewell | mckean75@yahoo.com | sent |  |
| 83 | 2026-08-31T20:59:51.259408+00:00 | Emilio Tapia | etapia@vtaig.com | sent |  |
| 84 | 2026-08-31T20:59:51.422178+00:00 | Gordon McKay | gordonfmckay@comcast.net | sent |  |
| 85 | 2026-08-31T20:59:51.613456+00:00 | Brian Beckman | brianbeckmanaz@gmail.com | sent |  |
| 86 | 2026-08-31T20:59:51.794089+00:00 | Amy Currie | amyc1220@outlook.com | sent |  |
| 87 | 2026-08-31T20:59:51.969479+00:00 | Jolene Lasley | jolene.lasley@gmail.com | sent |  |
| 88 | 2026-08-31T20:59:52.158478+00:00 | Alan Chesebrough | alanchesebrough@gmail.com | sent |  |
| 89 | 2026-08-31T20:59:52.357196+00:00 | Lorena Olivas | loretirei@yahoo.com | sent |  |
| 90 | 2026-08-31T20:59:52.600767+00:00 | Edward Paradine | ed.paradine@gmail.com | sent |  |
| 91 | 2026-08-31T20:59:52.775119+00:00 | Josh Lundgren | joshlundgren@msn.com | sent |  |
| 92 | 2026-08-31T20:59:52.998675+00:00 | Kimber Hanrahan | kimber.hanrahan@cox.net | sent |  |
| 93 | 2026-08-31T20:59:53.158486+00:00 | Trina Tyler | tnkhospitality@gmail.com | sent |  |
| 94 | 2026-08-31T20:59:53.359506+00:00 | Scott Muir | muir.scott62@gmail.com | sent |  |
| 95 | 2026-08-31T20:59:53.515247+00:00 | Heather Clement | hrkoontz@yahoo.com | sent |  |
| 96 | 2026-08-31T20:59:53.704556+00:00 | Tim McRath | unkletim@sbcglobal.net | sent |  |
| 97 | 2026-08-31T20:59:53.857557+00:00 | Siegfried Hess | sighess@comcast.net | sent |  |
| 98 | 2026-08-31T20:59:54.010228+00:00 | Allison Hymel | akhymel@gmail.com | sent |  |
| 99 | 2026-08-31T20:59:54.248028+00:00 | Seth & Ashley Wilson | ashleydwilson2020@gmail.com | sent |  |
| 100 | 2026-08-31T20:59:54.495506+00:00 | Jenny King | jennykingaz@gmail.com | sent |  |
| 101 | 2026-08-31T20:59:54.686253+00:00 | Ryan & Cristine Jacobs | cristine_jacobs@yahoo.com | sent |  |
| 102 | 2026-08-31T20:59:54.883834+00:00 | Thomas Brouse | tomb43@q.com | sent |  |
| 103 | 2026-08-31T20:59:55.048826+00:00 | Joe Jacobs | jjacobsaz@hotmail.com | sent |  |
| 104 | 2026-08-31T20:59:55.206587+00:00 | Bill Benson | bbenson66@gmail.com | sent |  |
| 105 | 2026-08-31T20:59:55.349210+00:00 | Megan Beck | meganbeck19@hotmail.com | sent |  |
| 106 | 2026-08-31T20:59:55.532402+00:00 | Frances LaPrairie | flaprairie@cox.net | sent |  |
| 107 | 2026-08-31T20:59:55.705613+00:00 | Jackie Logan | jmlogan3@yahoo.com | sent |  |
| 108 | 2026-08-31T20:59:55.863699+00:00 | Kat Israel | katinaz2000@yahoo.com | sent |  |
| 109 | 2026-08-31T20:59:56.037002+00:00 | Don Murray | ctire@ccinet.ab.ca | sent |  |
| 110 | 2026-08-31T20:59:56.204293+00:00 | John Segelbaum | lawdawg5814@earthlink.net | sent |  |
| 111 | 2026-08-31T20:59:56.379404+00:00 | Steve & Laura Grossman | abq262@gmail.com | sent |  |
| 112 | 2026-08-31T20:59:56.555240+00:00 | Linda Faye | andre1997_1@msn.com | sent |  |
| 113 | 2026-08-31T20:59:56.749645+00:00 | Matt & Keeley Siggins | sigginssquad@yahoo.com | sent |  |
| 114 | 2026-08-31T20:59:56.937239+00:00 | David & Lisa Galbreath | edonahuegalbreath@gmail.com | sent |  |
| 115 | 2026-08-31T20:59:57.273103+00:00 | Melissa McHenry | mellmchenry@gmail.com | sent |  |
| 116 | 2026-08-31T20:59:57.456189+00:00 | Deleted User | deleted-user-087681ae-d4df-4edd-988e-338b6a583ca6@example.invalid | sent |  |
| 117 | 2026-08-31T20:59:57.618015+00:00 | UNKNOWN | test+af6b5912@example.com | failed | ValidationError: Invalid `to` field. Please use our testing  |
| 118 | 2026-08-31T20:59:57.796778+00:00 | UNKNOWN | prepac66fa@example.com | failed | ValidationError: Invalid `to` field. Please use our testing  |


**Named customers the tenant has already heard from:**
- **Michelle Moore** (row #43 · `mimichaelmoore@yahoo.com` · sent at 20:59:44 UTC)
- **Scott Muir** (row search — `smuir@gmail.com` — sent 20:59:45 UTC)
- **Alan Chesebrough** (row search — `alanchesebrough@gmail.com` — sent 20:59:47 UTC)

_(exact row numbers depend on the sort — reference the timestamp column.)_

---

## 4 · Fix options (user adjudicates)

### Option A — Least invasive: hard-fail the offending test
- Rename `_login("admin@aquaterra.com", "password123")` in `test_bug_g_mass_messaging_filters.py` to seed a dedicated ephemeral tenant (or short-circuit at the top of the file: `pytest.skip("K72: production-tenant guard")`).
- Blast radius: 1 test file. **Zero prod-code changes.** The kill switch stays available for future incidents.
- Risk: any OTHER test that fans out to `all_active_customers` on `aquaterra` remains a footgun. Requires an audit of every mass-messaging test.

### Option B — Structural: add a test-tenant guard to `/api/mass-messaging/send`
- Add a `TEST_TENANT_IDS` env allow-list. The mass-messaging router refuses any `audience: "all_active_customers"` request whose `tenant_id` isn't in the allow-list UNLESS the request carries an `X-Confirm-Broadcast: <sha256(tenant.name)>` header.
- Blast radius: 1 router + 1 env var. Every test explicitly opts in.
- Risk: a legit admin sending a real broadcast has to know the header trick — bad UX. Better as a **test-mode** guard tied to `APP_ENV != production`.

### Option C — Recommended: **B + A combined**
1. Ship the test-tenant guard: mass-messaging router refuses `all_active_customers` fanout unless (a) the caller passes a per-request `X-Broadcast-Ack: 1` header AND (b) the caller's client IP is on `INTERNAL_ADMIN_ALLOWLIST_IPS`. In prod both hold; in CI the header is not set and the fanout returns 428.
2. Also convert `test_bug_g_mass_messaging_filters.py` to seed a synthetic tenant with 3 dummy customers whose emails route to `@example.local` (which the Resend allow-list already blocks). Delete the tenant post-suite.
3. Add a **CI-only** env `PYTEST_BLOCK_MASS_MESSAGING=1` — when set, the mass-messaging router itself refuses any request with `audience` prefixed `all_` regardless of headers.

Blast radius: 1 router + 1 test file + 1 CI env variable. Belt-and-braces: any single control failure still leaves two layers of protection.

**Recommendation:** ship Option C. It closes both the immediate hole (this test) AND the class of holes (any future test that forgets to guard). The kill switch remains as the emergency lever.

---

## 5 · Corrective customer follow-up email (draft — user to send from Resend)

**Subject:** A quick apology from Pool & Landscaping of Vistancia

**Body (plain text · brand voice — kept short + human):**

> Hi [First name],
>
> You recently received an email from us with the subject "no-filter" — that message was sent by mistake during an internal system test and shouldn't have reached your inbox. There's nothing you need to do, and your pool service is completely unaffected.
>
> We're sorry for the confusion, and we've already put safeguards in place so this doesn't happen again.
>
> If you have any questions about your service — or if that "no filter" wording made you wonder about something specific on your pool — please reply to this email or call us at **[SUPPORT_PHONE]**. We're happy to take a look.
>
> — The team at Pool & Landscaping of Vistancia
> cs@plofv.com · [SUPPORT_PHONE]

**Send list:** the 116 `sent` rows from section 3 (exclude the 2 `failed` bogus addresses + the "Deleted User" placeholder + the fixture `customer@aquaterra.com` demo mailbox → **~113 real customers**).

**Ops tip:** if the tenant sends this from the same `cs@plofv.com` address, threading in customer inboxes will keep it adjacent to the original — increasing the chance the recipient re-opens the thread and reads the correction.

---

## 6 · Timeline recap

- **Aug 31 2026 20:59:33 UTC** — first `no-filter` delivery hits Resend.
- **Aug 31 2026 20:59:57 UTC** — last delivery hits Resend (24-second burst, 118 attempts, 116 delivered).
- **Sep 1 2026** — user receives replies from Michelle Moore, Scott Muir, Alan Chesebrough asking what the email means.
- **Feb 2026 (this session)** — grep + delivery-log audit identifies `test_bug_g_mass_messaging_filters.py::test_send_no_filters_still_works` as culprit. K72 kill switch shipped (default OFF). No fix deployed; user must adjudicate between A/B/C.

---

## Appendix · Files touched by K72 kill switch

- `backend/services/comms_env_guard.py` — `guard_outbound(audience=...)` param + new `is_customer_email_kill_switch_on()` helper. K72 check fires before `APP_ENV=production` short-circuit.
- `backend/services/email/resend_adapter.py` — `send(audience="customer", ...)` param; kill switch enforced before `allow_off_allowlist=True` bypass.
- `backend/services/sms/rc_adapter.py` — `send(audience="customer", ...)` param.
- `backend/services/ringcentral/rc_client.py` — `send_sms(audience="customer", ...)` param.
- `backend/services/lead_notifications.py` — pass `audience="internal"` on admin lead-alert emails.
- `backend/services/daily_review_digest.py` — pass `audience="internal"` on tenant-owner digest.
- `backend/services/weekly_reputation_digest.py` — pass `audience="internal"` on tenant-owner digest.
- `backend/services/weekly_bulk_actions_digest.py` — pass `audience="internal"` on tenant-owner digest.
- `backend/services/leads_side_effects.py` — pass `audience="internal"` on internal admin notifications (email + SMS).
- `backend/routers/auth.py` — pass `audience="internal"` on password-reset email.
- `backend/.env` — `FEATURE_CUSTOMER_EMAIL_KILL_SWITCH=off` (default; flip to `on` in prod to activate).
- `backend/tests/test_k72_customer_email_kill_switch.py` — 20 pytest cases proving flag OFF (default), flag ON in every env, flag ON + audience=internal bypass, flag ON + allow_off_allowlist blocking for customer, and all truthy/falsy variants.

---

## RESOLVED · Fix shipped Feb-2026

User adjudicated **Option C** (belt-and-braces) + APP_ENV=preview flip (K72.a) + broadcast-confirm modal (K72.1). All three shipped in one iteration. Details:

- **K72.fix (Option C)** — See `/app/memory/PHASE_K72_FIX_MASS_MESSAGING_GUARDS.md`
- **K72.a (APP_ENV preview flip)** — See `/app/memory/PHASE_K72_A_PREVIEW_APP_ENV.md`
- **K72.1 (Broadcast confirm modal)** — See `/app/memory/PHASE_K72_1_BROADCAST_CONFIRM_MODAL.md`

**Verification:**
- `POST /api/mass-messaging/send` on the preview pod (this env) now returns HTTP 403 `K72_REAL_TENANT_NON_PROD_BLOCKED` — verified via curl.
- `pytest tests/test_bug_g_mass_messaging_filters.py` returns 1 skipped, 0 collected — verified.
- K72 kill switch remains available as the ultimate lever. Default OFF.

**Awaiting user:**
- Approve / edit the apology email draft (see section 5 above) and send from Resend to the 116 real recipients.
- Once approved, resume K70 tile theming → R1 Financial suite proper.
