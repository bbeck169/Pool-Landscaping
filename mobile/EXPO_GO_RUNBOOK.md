# Expo Go Mobile Testing Runbook — Phase 21 · Sub-item C

## What this gets you
A **QR-code-installable** version of the mobile app that runs against the
live preview backend (`https://poolscape-audit.preview.emergentagent.com`).
Point Expo Go at the QR code and the app boots in seconds. Perfect for
putting phones in front of teammates for internal testing without
touching TestFlight / Play Store.

## Prerequisites (one-time, local machine)

1. **Install Expo Go on each test phone**:
   - iOS: <https://apps.apple.com/app/expo-go/id982107779>
   - Android: <https://play.google.com/store/apps/details?id=host.exp.exponent>
2. **Get the repo checked out locally** on your dev laptop (any recent
   Node 18/20 works — no EAS account needed).
3. **Install once**:
   ```
   cd mobile
   yarn install --frozen-lockfile
   ```

## Why we can't run `eas update` from the pod (yet)

- `eas` CLI is **not installed** on this pod.
- `EXPO_TOKEN` env is **not set**.
- `mobile/app.json` has `slug=frontend`, **no `owner`**, and
  **no `updates` block** — `expo-updates` package is not installed.
- No `eas.json` exists.

Enabling `eas update` is a separate follow-up phase (needs an Expo
organization account + `eas init` + `expo-updates` install +
`runtimeVersion` policy). This runbook uses the local dev-server
tunnel path instead — same test outcome, zero infrastructure.

## Runbook (Expo Go via local tunnel)

From your dev laptop with the repo checked out:

```
cd mobile
yarn tunnel
```

That runs `expo start --tunnel`. Expected output:

```
› Metro waiting on exp://…
› Scan the QR code above with Expo Go (Android) or the Camera app (iOS)

› Web is waiting on http://localhost:19006

› Using Expo Go
› Press s │ switch to development build
› Press a │ open Android
› Press w │ open web

› Press ? │ show all commands

Logs for your project will appear below. Press Ctrl+C to exit.
```

**A large QR code renders in your terminal.** Point any test phone's
camera at it — Expo Go opens automatically and the app launches
against the live backend at
`https://poolscape-audit.preview.emergentagent.com`.

### If the QR code doesn't scan
- The tunnel uses ngrok-style URLs — usually
  `exp://<random>.exp.direct:80`. If your phone isn't on the same
  Wi-Fi as your laptop, tunnel mode still works over the internet.
- If `--tunnel` fails to start (rare), fall back to LAN mode:
  ```
  yarn start
  ```
  Phones must be on the same Wi-Fi as the laptop for LAN mode.

## What the tester phones see

- Full mobile UI logging into `super@aquaterra.com` /
  `manager@aquaterra.com` / `landscaper@aquaterra.com` /
  `customer@aquaterra.com` with `password123` — same accounts as
  web preview.
- All Phase 16 mobile-parity screens (schedule, invoices, AEO,
  reports).
- Phase 18 "My Inventory" screen at
  `/inventory/my-inventory` (tech-facing, cost-free).
- Phase 20 push tap-through routes `inventory_low_stock` bell taps
  to the correct screen.

## When to graduate to `eas update` (future phase)

Do this when you want:
- Over-the-air (OTA) updates that don't require re-scanning the QR
- Deep-links (`myapp://…`) that survive a cold start
- Testers who aren't on your Wi-Fi and don't want to install the
  tunnel dance every session

The migration will be a discrete phase covering: create Expo org →
add `owner` + `updates` + `runtimeVersion` to `app.json` → install
`expo-updates` → `eas init` → `eas update:configure` → publish first
update to `preview` channel. Not urgent — the tunnel is a fine
short-term testing path.

## Verified from the pod (Feb-2026)

- `expo@54.0.35` installed
- `@expo/cli` present in `mobile/node_modules`
- `EXPO_PUBLIC_BACKEND_URL=https://poolscape-audit.preview.emergentagent.com`
- Backend live: `/api/openapi.json` returns 200 with 1,397 paths
- All 4 seed logins return 200 via curl (see
  `backend/tests/test_demo_login_regression.py`)
