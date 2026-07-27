# Phase 34 · Task AA — Referral reward $25 → $55 credit (Mobile)

> Mobile Expo delegation brief. **Do not touch web/backend code**;
> the web + backend agent has already shipped this change.

## Web + backend changes shipped (for context)
1. **Copy** — every user-facing occurrence of `$25` tied to the referral
   program has been swapped to `$55 credit` on the web portal:
   * `ReferralSection.jsx` heading: "Refer a Friend — earn $55 credit"
     and body sub-copy.
   * `PortalReferralsPage.jsx` — sub-copy + native-share text.
   * `PortalWalkthrough.jsx` — tour step label.
   * `AdminReferralsPage.jsx` — void-confirm dialog language.
2. **Backend copy** — `services/lead_conversion_notifications.py` welcome
   HTML + M5c drip subject updated.
3. **Amount source** — the referral watcher + vesting promoter now
   read the reward amount from tenant configuration in this order:
   * `tenant.referral_reward_amount_cents` (legacy top-level, existing)
   * `tenant.settings.referrals.reward_amount_cents` (new nested)
   * legacy default `2500` cents
   PLOFV (aquaterra) is idempotently seeded on server boot to
   `referral_reward_amount_cents = 5500` (=$55) in both locations.
   **Historical credits are NOT retroactively adjusted** — existing
   rows in `service_credits` keep their original `amount_cents`.

## Mobile parity task
On the Expo app:

* Refer a Friend heading + body copy: change "$25" → "$55 credit"
  wherever it appears (Referrals home tile, dedicated referrals
  screen, share-sheet text, program-detail screens).
* Any hardcoded numeric reward on mobile should read from the backend
  (the summary/referral endpoints already surface the current tenant
  reward); otherwise, hardcode `$55` as the interim value with a
  `TODO(server-driven)` comment.
* Ensure share-sheet native `title` / `message` fallbacks say
  "$55 off" not "$25 off".
* Walkthrough / onboarding step for referrals: update to
  "Refer a Friend — earn $55 credit".

## Verification checklist
- [ ] No "$25" copy remains on any referral-related mobile screen.
- [ ] Share sheet mentions "$55 off".
- [ ] Onboarding tour step reads "earn $55 credit".
- [ ] No regression on credit-balance display (real credits still
      show their historical amounts — mobile just displays the
      backend-provided value).

Ship as a single mobile PR referencing this brief.
