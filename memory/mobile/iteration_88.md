# Iteration 88 — Dispatch A Test Fix

## What was implemented
- Fixed Jest API mock hoisting bug in both Dispatch A test suites
- Root cause: `jest.mock()` hoisted above `const mockGet = jest.fn()` by babel-jest, causing `api.get` to be `undefined` in the mock factory
- Solution: Use inline `jest.fn()` inside the `jest.mock()` factory, then retrieve references via `import { api } from "@/src/api"; const mockGet = api.get as jest.Mock`
- Fixed ChaseStalledInvitesSheet mock to respond to `visible` prop for the "opens sheet" test case

## Cleanup performed
- Removed 2 `console.log` debug statements from PortalOnboardingHealthTile.tsx
- Removed unused `formatCustomerName` import from customers.tsx
- Deleted temporary `debug-tile.test.tsx` debug file
- Updated AUDIT_MOBILE_PARITY_TRIO.md with final deliverable checklist

## Test results
- 14/14 tests passing (8 onboarding-health-tile + 6 chase-stalled-invites)
- All source files lint clean
- Test files have expected lint warnings (import/first, no-require-imports) due to Jest mock hoisting pattern

## Dependencies installed
- None

## Known issues
- None remaining for Dispatch A

## Deferred
- Feature 3 (Temp Password / Portal Access Panel) — Dispatch B, not started
