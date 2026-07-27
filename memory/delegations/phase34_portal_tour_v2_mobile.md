## Delegation Brief · Phase 34 · Customer Portal Tour v2 (mobile)

**From:** Web team · Phase 34 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** English only.
**Status:** Web shipped (step-list extended). Mobile parity outstanding.

---

### What changed on web

`/app/frontend/src/pages/portal/PortalWalkthrough.jsx` — the STEPS
array now walks the customer through the reorganised portal home
plus the Task-34 additions:

| # | Anchor (`data-tour-id`)      | Route                       | Copy |
|---|------------------------------|-----------------------------|------|
| 1 | `portal-cta-row`             | `/portal/home`              | Call Now + Request Service |
| 2 | `status-circles`             | `/portal/home`              | Balance / past due / credit / next service |
| 3 | `last-visit-card`            | `/portal/home`              | Your most recent visit summary |
| 4 | `portal-ai-section`          | `/portal/home`              | Ask a Concierge · Billy + Skedra |
| 5 | `portal-referral-section`    | `/portal/home`              | Refer a Friend — earn $25 |
| 6 | `business-card`              | `/portal/home`              | Contact card / NFC handoff |
| 7 | `communications-list`        | `/portal/messages`          | Message history |
| 8 | `invoices-list`              | `/portal/invoices`          | Invoices |
| 9 | `estimates-list`             | `/portal/estimates`         | Estimates |
| 10| `service-reports-list`       | `/portal/service-reports`   | Service reports · grouped by date |
| 11| `request-service-form`       | `/portal/request-service`   | Free-text visit request |
| 12| `payment-method-panel`       | `/portal/payment-method`    | Payment method |

The `data-tour-id` attributes for the three NEW anchors
(`portal-cta-row`, `last-visit-card`, `portal-ai-section`) have also
been added to their target elements so the spotlight overlay finds
them.

### Version bump

The web tour still keys off `user.has_seen_customer_tour` (bool). The
next iteration will bump this to a versioned flag
(`portal_tour_completed_v1 → v2`) so existing customers who already
dismissed v1 will see the extended tour once. This is a **follow-up**
(tracked separately in `/app/memory/todo_portal_tour_v2_versioning.md`)
so the mobile agent can build the same behavior in parallel without
waiting on the backend flag change.

Restart affordance already exists on
`/app/frontend/src/pages/portal/PortalPreferences.jsx` (search
"Replay the first-login walkthrough") — mobile should keep the
equivalent affordance on its Profile / Preferences screen.

### Mobile task

Mobile Expo customer portal — `/app/mobile/app/(portal)/*`:

1. Locate the mobile tour engine (whatever tour library the app
   uses — react-native-copilot, react-native-portal-tour, or a
   custom implementation).
2. Update the mobile step list to match the web STEPS table above.
3. Ensure each mobile screen tags its equivalent target element with
   a `testID` that matches the web `data-tour-id` value (e.g.
   `testID="portal-cta-row"`, `testID="last-visit-card"`,
   `testID="portal-ai-section"`, `testID="portal-referral-section"`).
4. Preserve Prev / Next / Skip Tour controls.
5. Auto-scroll target into view before highlighting (most RN tour
   libraries do this with `scrollTo` — verify).
6. Trigger conditions: run on first login for a `role=customer`
   user. Persist a `portal_tour_completed_v2` flag in AsyncStorage
   keyed by user_id so it doesn't replay on every reload. When the
   backend flips to versioned flag, mobile should read from
   `/auth/me` payload.
7. Add a "Restart tour" pressable on the mobile Profile screen so
   the customer can replay on demand.

### Guardrails

- English-only.
- Do NOT touch admin / dispatch mobile surfaces — customer portal only.
- Keep the step count at 12 to match web.

### Reference

- Web tour engine:    `/app/frontend/src/pages/portal/PortalWalkthrough.jsx`
- Web preferences:    `/app/frontend/src/pages/portal/PortalPreferences.jsx`
                        (search "Replay the first-login walkthrough")
- Backend status API: `GET /api/customer-portal/walkthrough/status`
                        + `POST /api/customer-portal/walkthrough/complete`
