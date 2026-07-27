## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Portal Home — Top CTA Row (Call Now + Request Service side-by-side)

**From:** Web team · Phase 34 · Feb 2026 · Task K
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** English only.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on web

`/app/frontend/src/pages/portal/PortalHome.jsx`

A new top row now renders as the **first block of the portal home
content area**, above the "Welcome back / Hi, {name}" hero card:

- Row wrapper: `data-testid="portal-cta-row"`, `flex flex-col sm:flex-row gap-3 md:gap-4 mb-4`
- Left cell: existing `<CallNowButton />` (green phone CTA, unchanged behaviour), wrapped in a `flex-1 min-w-0` div with `data-testid="portal-cta-call"`
- Right cell: existing `<button data-testid="portal-request-service-btn">` (brand gradient CTA that opens the Request Service modal). Now uses `flex-1 min-w-0 px-4 py-3` and `minHeight: 48px` so it visually matches the Call Now button height.
- On mobile widths (`< sm`) the two stack vertically full-width.
- On `sm` and above they render side-by-side, equal-flex.

Both buttons' onClick handlers are UNCHANGED — Call Now still dials the
tenant support phone, Request Service still opens the (simplified,
free-text) request modal.

The two OLD standalone occurrences of these buttons further down the
page (the Call Now div right above quick actions + the Request Service
div right after the ToS banner) have been removed. Comments were left
in place so the DOM order is easy to reason about.

New render order on the portal home (top → bottom):
1. **Top CTA row**: `[Call Now]` `[Request Service]`
2. Welcome-back hero card
3. Stat circles (Balance Due / Past Due / Credit / Next Service)
4. Alert row (Overdue / Pending estimates / Unread messages)
5. Terms of Service banner (conditional)
6. Quick Actions grid
7. **Ask a Concierge** (Task from earlier brief — sits directly above Refer a Friend)
8. **Refer a Friend**
9. My Referrals
10. Business Card
11. Last-visit card

---

### What we need from mobile

Corresponding mobile home screen: `/app/mobile/app/(portal)/index.tsx`
(or whichever file the Expo portal Home uses today — the drawer /
`_layout.tsx` will confirm).

1. Add a new top row rendering **before** the hero card, with two
   equal-flex buttons in a horizontal `View` on tablets/large phones,
   stacked in a vertical `View` on narrow phones. React Native
   equivalent:

   ```tsx
   <View
     testID="portal-cta-row"
     style={{
       marginBottom: 12,
       flexDirection: 'row',       // stacks vertically on narrow via
                                    // a small useMediaQuery / Dimensions
                                    // check — see below
       gap: 12,
       flexWrap: 'wrap',
     }}
   >
     <View style={{ flex: 1, minWidth: 220 }} testID="portal-cta-call">
       <CallNowButton />
     </View>
     <Pressable
       testID="portal-request-service-btn"
       onPress={() => setRequestOpen(true)}
       style={{
         flex: 1,
         minWidth: 220,
         minHeight: 48,
         paddingHorizontal: 16,
         paddingVertical: 12,
         borderRadius: 12,
         backgroundColor: BRAND_GRADIENT_FALLBACK,
         alignItems: 'center',
         justifyContent: 'center',
         flexDirection: 'row',
         gap: 8,
       }}
     >
       <Plus size={16} color="#fff" />
       <Text style={{ color: '#fff', fontWeight: '700', fontSize: 14 }}>
         Request Service
       </Text>
     </Pressable>
   </View>
   ```

   For the actual gradient, use `expo-linear-gradient` wrapped around
   the Pressable content.

2. Narrow-screen stacking: use `Dimensions.get('window').width < 480`
   (or the project's existing responsive helper) to flip
   `flexDirection` from `row` to `column`.
3. Remove the OLD Call Now + Request Service buttons from their prior
   positions so they aren't duplicated.
4. Preserve all existing behaviour on tap (Call Now → RN `Linking` to
   `tel:` URI; Request Service → open request modal / navigate to the
   Request screen).
5. `testID` parity is mandatory:
   - `portal-cta-row`
   - `portal-cta-call`
   - `portal-request-service-btn`

---

### Guardrails

- Do NOT touch backend endpoints.
- Do NOT change the onPress handlers — behaviour is unchanged.
- English-only strings + commits.
- Keep the two buttons visually equal-emphasis and equal-height. Call
  Now stays green; Request Service stays brand gradient.
- Ensure the layout is safe on very narrow devices (iPhone SE, ~320px
  width) — stacked vertically with full-width children.

---

### Reference paths

- Web page:       `/app/frontend/src/pages/portal/PortalHome.jsx`
- CTA row block:  search `data-testid="portal-cta-row"`

### Deploy

- Mobile: OTA / EAS update after merge. No native modules required.
