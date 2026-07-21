# Iteration 6 — Mobile Parity Slice (Tech + Admin Roles)

## Date: 2026-07-20

## What Was Implemented

### PART A — Tech Role Screens & Components
| Component | File | Description |
|-----------|------|-------------|
| WeatherWidget | `src/components/weather/WeatherWidget.tsx` | Current conditions, hourly/daily forecast, Radar embed via WebView |
| RainFlag | `src/components/weather/RainFlag.tsx` | Badge shown when rain is expected within 4 hours |
| MultiContact | `src/components/customers/MultiContact.tsx` | Read-only viewer for phone numbers (mapped from `number_e164`) and emails (mapped from `address`) on customer detail |
| CustomerTasks | `src/components/customers/CustomerTasks.tsx` | Tasks tab on customer detail, fetches from `/customer-tasks?customer_id=` |
| ServiceNotes | `src/components/customers/ServiceNotes.tsx` | Editable service notes per customer, GET + PATCH to `/customers/:id/service-notes-for-schedule` |
| SendCreateSheet | `src/components/customers/SendCreateSheet.tsx` | Action sheet FAB on customer detail for quick-create actions |
| Campaigns (screen) | `app/campaigns.tsx` | Read-only campaigns list, fetches `/campaigns` |
| VIP badge | Inline in `app/customer/[id].tsx` | Read-only VIP indicator on customer detail header |

### PART B — Admin Role Screens & Components
| Component | File | Description |
|-----------|------|-------------|
| AIDockDrawer | `src/components/ai/AIDockDrawer.tsx` | Slide-up drawer with AI employee list, chat, actions queue |
| CreditsBudgetChip | `src/components/ai/CreditsBudgetChip.tsx` | Shows remaining AI credits in dashboard header |
| WeatherWidget | (shared with Tech) | Same weather widget, rendered on Admin dashboard |

### Role Gating (CRUCIAL)
- Admin dashboard (`app/(app)/index.tsx`): renders WeatherWidget + CreditsBudgetChip + AI FAB
- Tech dashboard (`app/(app)/index.tsx`): renders WeatherWidget ONLY; AI Dock, credits chip, and all AI-adjacent UI are **strictly hidden**
- Customer role: sees NONE of the above components
- Gating is done via `user.role` checks in the dashboard and layout files

### API Files Created
| File | Endpoints |
|------|-----------|
| `src/api/weather.ts` | `GET /tenants/mine/location`, `GET /weather/current`, `GET /weather/hourly`, `GET /weather/daily`, `GET /weather/radar` |
| `src/api/aiDock.ts` | `GET /ai-employees`, `GET /ai-employees/:eid`, `GET /ai-credits/balance`, `GET /ai-employees/:eid/conversations`, `POST /ai-employees/:eid/conversations`, `GET /ai-employees/:eid/conversations/:cid/messages`, `POST /ai-employees/:eid/conversations/:cid/messages`, `POST /ai-employees/chat`, `GET /ai-employees/actions`, `POST /ai-employees/actions/:aid/approve`, `POST /ai-employees/actions/:aid/reject` |

## Bug Fixed
- **MultiContact.tsx crash**: The component received phone/email entries as objects (`{number_e164, label}` / `{address, label}`) but tried to render them as plain strings. Fixed by mapping `.number_e164` and `.address` respectively.

## Web-to-Mobile Mapping Decisions
- Web's `WeatherWidget` → mobile `WeatherWidget` + `RainFlag` (same endpoints, StyleSheet instead of CSS)
- Web's AI Dock sidebar → mobile `AIDockDrawer` (bottom-sheet pattern instead of side panel)
- Web's credits display → mobile `CreditsBudgetChip` (compact chip in dashboard header)
- Web's campaigns page → mobile `campaigns.tsx` (read-only FlatList)
- Web's customer detail tabs → mobile tabs within `customer/[id].tsx` (Tasks, Notes sections)

## Files Modified
- `mobile/app/(app)/_layout.tsx` — added hidden routes for campaigns
- `mobile/app/(app)/index.tsx` — role-gated dashboard widgets
- `mobile/app/(app)/schedule/calendar.tsx` — weather integration on calendar
- `mobile/app/campaigns.tsx` — new campaigns screen
- `mobile/app/customer/[id].tsx` — Tasks, MultiContact, ServiceNotes, SendCreate, VIP badge

## Dependencies Installed
- None new (reused existing `react-native-webview` for Radar embed)

## Testing Performed
- Screenshot: Admin dashboard — WeatherWidget ✅, AI FAB ✅, CreditsBudgetChip ✅
- Screenshot: Tech dashboard — WeatherWidget ✅, AI Dock HIDDEN ✅, Credits HIDDEN ✅
- Screenshot: Tech customer detail — Tasks ✅, ServiceNotes ✅, SendCreate FAB ✅, MultiContact ✅ (after fix)
- No regressions detected

## Known Issues
- None
