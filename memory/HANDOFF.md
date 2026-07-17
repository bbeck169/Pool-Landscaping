# HANDOFF — most recent shipped phase

## Phase 56.9 · Chlorine tabs default + Luis Marquez rename (Feb 2026)

**Items shipped in this batch**:
1. **Chlorine Tabs = always-default** in the AI dosing recommender.
   Overrides live on the customer profile (`chemical_preferences.no_tabs`
   or `chemical_preferences.prefer_liquid_chlorine`). Rapid-boost and
   tab-rotation auto-demote paths removed for predictability.
2. **Luis Marquez** — `landscaper@aquaterra.com` seed user renamed
   (DB drift-fix applied; seed script already had correct value).
   `test_credentials.md` updated.
3. **Zillow explanation** (investigation only — no code change):
   `require_admin` on `property.py` / `d2d.py` / `zillow_admin.py` is
   intentional. Tech/customer 403s surface the "Admin access required"
   banner because Zillow enrichment is a rate-limited paid API and
   admin-gated to protect the budget. Waiting on explicit go-ahead
   before changing this RBAC.

**Verification**:
- 20/20 dosing unit tests passing (`test_phase56_5_dosing.py`).
- Live payload: fc=2.0 → `Chlorine tabs qty=4 unit=tabs form=tabs`
  reason "Tabs recommended for steady residual…".
- Curl login for `landscaper@aquaterra.com` returns `name: "Luis Marquez"`.
- `bash /app/scripts/preflight.sh` → exit 0.

**Queued next**:
- **Phase 56.10** — Visible algae field on wizard step 1 + AI algae
  remediation entries (calcium hypochlorite lbs, polyquat 60 oz,
  high-pH ordering guard, `category: "algae_remediation"` on payload
  items, brush + 24h filter run notes).
- **Phase 56.11** — Customer Equipment Photo Library (11-type enum,
  ≤4 photos per type, admin-only delete, tenant isolation, web +
  mobile parity, `/api/customers/{id}/equipment-photos` endpoints).

**Not queued (deferred/parked)**:
- Phase 56.7 mobile pool wizard port — awaiting confirmation on the
  original nav-visibility premise (GlobalMenu already accessible on
  the mobile checklist route per Phase 43).
- Mobile Add-Team-Member sheet, mobile Job Request UI, mobile "In
  progress" job-card pill.
- Zillow RBAC relaxation for pool/landscape techs (Phase 56.9 item 3
  investigation — awaiting explicit sign-off).
