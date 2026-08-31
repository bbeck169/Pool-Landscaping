# Iteration 49 — Subscriptions CRUD (B4) Validation & Test Fix

## Date: 2026-08-31

## What was done

### Context
The previous agent (iteration 48) fully implemented the Subscriptions B4 feature — UI component, API layer, test files — but reported it as "scaffolded only" and never ran the tests. This iteration validated everything was working and fixed the one failing test.

### 1. Validated Existing Implementation
- `src/components/subscriptions/SubscriptionsSection.tsx` — 830 LOC, fully functional with:
  - Subscription list with status chips, formatted plan labels, quantity, period end dates
  - Create Modal with price picker, quantity, payment method selector, trial days
  - Edit Modal with quantity + cancel-at-period-end toggle
  - Cancel Modal with at_period_end / immediate radio selection (single-click, no typed confirm)
  - Offline banner + disabled actions when disconnected
- `src/api/subscriptions.ts` — 49 LOC, all 5 endpoints wired
- `app/customer/[id].tsx` — Component mounted at line 481 (admin-gated)

### 2. Fixed Test Bug
- `__tests__/subscriptions-mobile-create.test.tsx` test #3 was failing because it pressed the submit button before the async prices loaded
- Fix: Changed `waitFor` to wait for `subscriptions-create-price-price_A` testID instead of just the submit button

### 3. Fixed Lint Warnings
- Removed unused imports `ActivityIndicator` and `api` from SubscriptionsSection.tsx

## Test Results
| Suite | Tests | Status |
|-------|-------|--------|
| subscriptions-mobile-list.test.tsx | 4/4 | ✅ |
| subscriptions-mobile-create.test.tsx | 3/3 | ✅ |
| subscriptions-mobile-edit.test.tsx | 2/2 | ✅ |
| subscriptions-mobile-cancel.test.tsx | 4/4 | ✅ |
| subscriptions-mobile-offline.test.tsx | 2/2 | ✅ |
| **Total** | **15/15** | ✅ |

## Files modified
- `__tests__/subscriptions-mobile-create.test.tsx` — Fixed test timing bug
- `src/components/subscriptions/SubscriptionsSection.tsx` — Removed 2 unused imports

## Web-to-Mobile mapping (confirmed parity)
| Web | Mobile | Notes |
|-----|--------|-------|
| `SubscriptionsPanel.jsx` | `SubscriptionsSection.tsx` | Full feature parity |
| `<select>` for prices | Radio picker list | Native pattern |
| `<select>` for PM | Radio picker list | Native pattern |
| `<input type="checkbox">` | `<Switch>` | Native toggle |
| `<input type="radio">` | Custom radio rows | Native pattern |
| `Toast` component | `Alert.alert()` | Native pattern |
| `data-testid` | `testID` | Same naming convention |

## Known Issues
- Expo preview tunnel sleeps frequently (pre-existing, not a code issue)
