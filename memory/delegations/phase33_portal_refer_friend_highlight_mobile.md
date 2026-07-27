## Delegation Brief · Phase 34 · Refer a Friend visual highlight (mobile)

**From:** Web team · Phase 34 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** English only.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on web

`/app/frontend/src/pages/portal/ReferralSection.jsx` — the neutral
white "Refer a Friend" card is now a bold gradient hero:

- **Gradient:** `linear-gradient(135deg, #7C3AED 0%, #A855F7 55%, #EC4899 100%)`
  (purple → violet → magenta).
- Container: `rounded-3xl p-6 my-4 shadow-lg`.
- Heading text: `text-xl font-black`, colour `#FFFFFF`.
- Body / helper: `rgba(255,255,255,0.92)`.
- Heading updated: **"Refer a Friend — earn $25"**.
- Helper adds the reward note: "You'll get $25 in credit after their
  first paid month."
- `data-testid="portal-referral-section"` preserved. New
  `data-tour-id="referrals-panel"` added so Tour v2 can spotlight it.

WCAG-AA: pure white on `#7C3AED` gives 4.83:1 (bold + ≥14px passes AA).

### Mobile task

On the mobile portal Home referral component:

1. Wrap the referral card in an `expo-linear-gradient`:
   ```tsx
   <LinearGradient
     colors={["#7C3AED", "#A855F7", "#EC4899"]}
     start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
     style={{ borderRadius: 24, padding: 20, marginVertical: 12,
              shadowColor: "#000", shadowOpacity: 0.15,
              shadowOffset: {width: 0, height: 6}, shadowRadius: 12,
              elevation: 6 }}
     testID="portal-referral-section"
   >
     …existing content, all text colour #FFFFFF…
   </LinearGradient>
   ```
2. Update the heading text: `"Refer a Friend — earn $25"`.
3. Update the helper copy: adds the $25 reward line.
4. Set every text child inside the gradient to `color: '#FFFFFF'`
   (or `rgba(255,255,255,0.92)` for secondary text).
5. Keep the "Send Referral" button visually punchy — use a solid
   white pill button with brand-purple text for max contrast.
6. Keep `testID`s stable so QA regression suites keep working.
7. Do NOT change any onPress handlers, endpoint calls, or props.

### Guardrails

- English-only.
- No backend touches.
- Contrast check: any body text darker than `rgba(255,255,255,0.85)`
  will fail AA against the mid-magenta stop — keep to white variants.

### Reference

- Web: `/app/frontend/src/pages/portal/ReferralSection.jsx`
