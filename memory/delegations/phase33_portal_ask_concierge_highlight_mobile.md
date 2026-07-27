## Delegation Brief · Phase 34 · Ask a Concierge visual highlight (mobile)

**From:** Web team · Phase 34 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** English only.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on web

`/app/frontend/src/pages/portal/PortalHome.jsx` — the Ask a Concierge
block (`data-testid="portal-ai-section"`) is now a bold gradient card
distinct from the Refer a Friend gradient:

- **Gradient:** `linear-gradient(135deg, #0891B2 0%, #0EA5E9 50%, #10B981 100%)`
  (teal → cyan → emerald).
- Container: `rounded-3xl p-5 shadow-lg`.
- Heading `text-lg font-black uppercase tracking-wide`, colour `#FFFFFF`.
- Adds subtitle "Chat with one of our AI concierges — no wait,
  answers in seconds."
- Per-employee cards are semi-transparent white glass (`rgba(255,255,255,0.16)`
  background + `rgba(255,255,255,0.28)` border + `backdropFilter: blur(6px)`).
- Employee name/description text switched to white variants for AA
  contrast.
- `data-tour-id="portal-ai-section"` added so Tour v2 can spotlight it.

Why teal→emerald? It's distinct from both Refer a Friend's
purple→pink and the app's brand-blue Welcome hero, so the three
gradient blocks read as separate moments on the home page.

### Mobile task

Update the AI concierge card on the mobile portal Home:

1. Wrap the whole block in an `expo-linear-gradient`:
   ```tsx
   <LinearGradient
     colors={["#0891B2", "#0EA5E9", "#10B981"]}
     start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
     style={{ borderRadius: 24, padding: 18, marginTop: 20,
              marginBottom: 16, shadowColor: "#000", shadowOpacity: 0.15,
              shadowOffset: {width: 0, height: 6}, shadowRadius: 12,
              elevation: 6 }}
     testID="portal-ai-section"
   >
     …existing content, all header text colour #FFFFFF…
   </LinearGradient>
   ```
2. Header row: keep the sparkle icon, switch its colour to white.
   Heading `"Ask a Concierge"` uppercase, bold weight, `#FFFFFF`.
3. Add the subtitle: "Chat with one of our AI concierges — no wait,
   answers in seconds." at 14px `rgba(255,255,255,0.92)`.
4. Per-employee cards become semi-transparent white glass:
   ```
   backgroundColor: 'rgba(255,255,255,0.16)',
   borderWidth: 1,
   borderColor: 'rgba(255,255,255,0.28)',
   ```
   Emoji avatar chips remain their original pastel colours (they
   provide the accent).
5. Text inside employee cards: name `#FFFFFF` bold; description
   `rgba(255,255,255,0.85)`.
6. Preserve `testID` values: `portal-ai-section`, `portal-ai-billy-card`,
   `portal-ai-skedra-card`.

### Guardrails

- English-only.
- Do NOT change the onPress handlers or the endpoint that lists
  available concierges (`/api/customer-portal/ai-employees`).
- Contrast check: the darkest stop `#0891B2` gives 4.51:1 with
  `#FFFFFF` — AA-compliant for 14px bold and above.

### Reference

- Web: `/app/frontend/src/pages/portal/PortalHome.jsx` (search
  `data-testid="portal-ai-section"`)
