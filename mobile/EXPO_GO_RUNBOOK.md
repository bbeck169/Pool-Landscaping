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

---

## Phase 38b · Feb-2026 — Live dispatch map (Mapbox / dev-client only)

The dispatch board's **Live Positions** section uses
[`@rnmapbox/maps@^10.1.34`](https://github.com/rnmapbox/maps) — a
native module. **This does NOT work in plain Expo Go**; you must
rebuild the dev client. Devs still on Expo Go see a graceful
"Live map requires the dev client" banner (testID
`dispatch-live-map-fallback`) and the rest of the board keeps
working.

### One-time enable

1. **Get a Mapbox access token** — sign in at
   https://account.mapbox.com/access-tokens/ and copy the default
   public token (starts with `pk.`). The free tier is 50k monthly
   loads — plenty for this app.

2. **Set the env var** in `mobile/.env`:

   ```
   EXPO_PUBLIC_MAPBOX_TOKEN=pk.your_actual_token_here
   ```

   The token is already referenced from `mobile/app.json` under
   `plugins → @rnmapbox/maps → RNMapboxMapsDownloadToken` and
   `extra.mapboxToken`. Both read the same env var at prebuild
   time.

3. **Install the dep** (already added to `package.json` — run once
   locally if you're on a fresh checkout):

   ```bash
   cd mobile
   yarn install
   ```

4. **Prebuild + rebuild the dev client**:

   ```bash
   cd mobile
   npx expo prebuild --clean
   # then rebuild the native dev client — pick one:
   eas build --profile development --platform ios
   eas build --profile development --platform android
   ```

   The prebuild step mutates `ios/` + `android/` folders with the
   Mapbox config plugin. Commit the resulting native folders IF
   your workflow tracks them; otherwise `.gitignore` them and let
   EAS regenerate on each build.

5. **Verify** by opening the app on the freshly-installed dev
   client, going to Dispatch → Board. You should see the Live
   Positions section with the map rendered (or "GPS feed offline"
   if `/api/gps/live-positions` isn't returning data yet). The
   fallback banner should NOT show.

### Troubleshooting

- **"Native module RNMBXModule not found"** — you're still on Expo
  Go. Run steps 3–4 above.
- **Empty map with no tiles** — token isn't reaching the build.
  Verify with `npx expo config --json | grep mapbox` — you should
  see the token literal, not `$EXPO_PUBLIC_MAPBOX_TOKEN`.
- **"Live map unavailable — set EXPO_PUBLIC_MAPBOX_TOKEN"** —
  banner rendered by the wrapper when it can't find the token at
  runtime. Restart Metro after editing `.env`.

### CI note

The prebuild step is heavy. If you're running `expo prebuild` in
CI and want to skip Mapbox specifically (e.g. because Mapbox's
private token download requires auth), set
`NO_MAPBOX_PREBUILD=true` and add a small guard to the config
plugin loader.

### Rollback

To disable the map entirely without touching mobile code:
- Set `EXPO_PUBLIC_MAPBOX_TOKEN=` (blank) and rebuild. The wrapper
  will render `dispatch-live-map-no-token` and the pins won't fetch.
- To fully remove: `yarn remove @rnmapbox/maps` + delete the plugin
  entry from `app.json` + delete
  `mobile/src/components/dispatch/LiveTechPinsMap.tsx` and
  `LiveTechPinsWrapper.tsx` + drop the import from
  `mobile/app/(app)/dispatch/board.tsx`.

