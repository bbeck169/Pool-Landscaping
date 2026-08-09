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

## Phase 49 · Feb-2026 — Lana voice input requires the dev-client build

Adding `expo-speech-recognition` to the mobile bundle pulls in a native
iOS + Android module. Same class of change as Phase 38b's `@rnmapbox/maps`.

**Impact**:
- Voice input on `mobile/app/os/lana.tsx` (the mic button) requires the
  EAS **dev-client** build. In plain Expo Go it degrades gracefully to
  an "Voice unavailable" alert; text input still works.
- Every other Phase 49 feature (todos panel, schedule-intent confirm
  flow, reminder-SMS cron) works in Expo Go — voice is the ONLY
  dev-client-gated bit.

**Rebuild the dev-client:**

```bash
cd mobile
npx expo prebuild --clean          # regenerates ios/ and android/
eas build --profile development --platform ios     # or --platform android
```

Install the resulting `.ipa` / `.apk` on the test device. QR-code
Metro launcher works with the dev-client the same way it does with
Expo Go, but the native modules resolve correctly.


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


---

## Phase 51c · Walkie-Talkie native audio + push (Feb 2026)

**Native module added:** `expo-audio@~1.1.1` (Expo SDK 54 compatible). Auto-installed via `npx expo install expo-audio`. Config plugin auto-added to `app.json` with iOS microphone permission text.

**Expo Go does NOT ship the walkie-talkie microphone recorder.** `expo-audio` is a bare-native module (like `@rnmapbox/maps` from Phase 38b and `expo-speech-recognition` from Phase 49) — you must rebuild the custom dev-client:

```bash
# From /app/mobile (or wherever your local checkout is):
eas build --profile development --platform ios
eas build --profile development --platform android
```

Distribute the resulting dev-client build via TestFlight internal / Google internal-testing exactly the same way Phase 38b Mapbox + Phase 49 speech-recognition did. Testers who previously installed the dev-client still need to reinstall to pick up the new `expo-audio` native module.

**Push notifications:**
- Backend fan-out is env-gated by `WALKIE_PUSH_LIVE=1` — DEFAULT is dry-run (logs the push payload, no network hit). This keeps Expo Go / preview / local dev quiet.
- To enable real pushes on the live server: set `WALKIE_PUSH_LIVE=1` AND `EXPO_PUSH_ACCESS_TOKEN=<your-expo-access-token>`. Both must be present.
- Device push tokens are stored via the existing `POST /api/mobile-tokens` endpoint (Phase 20). No new endpoint was added.
- Payload data: `{"type": "walkie", "channel_id": "…", "message_id": "…"}`. Tapping the push deep-links to `/walkie/{channel_id}` via the notification-route resolver (Phase 20 `notificationRoutes.ts`).

**Audio recording specifics on the dev-client:**
- iOS records in AAC / `.m4a` (`audio/mp4`).
- Android records in AAC / `.m4a` (`audio/mp4`).
- Both are already whitelisted by the Phase 51a backend (`POST /api/walkie/messages`).
- 30-second hard cap enforced client-side; server-side cap enforced on upload.

**Quick smoke test on device:**
1. Log in as `mike@aquaterra.com` (pool tech) — walkie entry appears.
2. Open All-Hands — mic is greyed with "Only admins can broadcast to all-hands".
3. Open Pool Team — hold the mic 2-3 s, release. Clip appears in the timeline.
4. Log in as `admin@aquaterra.com` on a second device — the clip auto-plays if that device is on the Pool Team screen and unmuted.


---

## Phase 52.1c · Walkie live streaming (WebRTC · Feb 2026)

**Native modules added:**
- `react-native-webrtc@124.0.6` — WebRTC peer connections, mic capture, ICE handling.
- `@config-plugins/react-native-webrtc@13.0.0` — Expo prebuild plugin that wires the iOS pods + Android gradle bits.

Both are **dev-client only** (same class as Phase 38b Mapbox / Phase 49 speech-recognition / Phase 51c expo-audio). Expo Go will crash on `RTCPeerConnection` import; the live panel gracefully sits behind the "Live channel" toggle so testers on Expo Go can keep using async clips.

**One-time rebuild:**

```bash
cd mobile
npx expo prebuild --clean          # regenerates ios/ + android/ with the new plugin
eas build --profile development --platform ios
eas build --profile development --platform android
```

Distribute via TestFlight internal / Google internal-testing exactly like the prior phases.

**Platform permission diff** (already applied to `app.json`):

*iOS `expo.ios.infoPlist`*
- `NSMicrophoneUsageDescription` updated to include walkie-talkie live-session copy.
- `UIBackgroundModes` extended with `"audio"` so the live session survives the OS locking the screen briefly (mic in a live channel).

*Android `expo.android.permissions`*
- `FOREGROUND_SERVICE_MICROPHONE` — Android 14+ requires this for foregrounded mic capture; without it, opening the live panel crashes on Android 14 devices.
- `MODIFY_AUDIO_SETTINGS` — required by `react-native-webrtc` for routing audio through the earpiece/speaker.

**Product decisions (locked):**
- **PTT only on mobile in 52.1c.** VOX (voice-activated) is desktop-only in this slice — see the DECISION comment in `mobile/src/pages/walkie/LivePanel.tsx`. `react-native-webrtc` doesn't ship a WebAudio-equivalent `AnalyserNode`, and adding a native VAD module (or driving VOX through `expo-audio`'s `metering` on a parallel recorder) adds a battery hit that's out of scope for the initial mobile slice. VOX moves to Phase 52.1e follow-up.
- The VOX pill in the mobile live panel is rendered but disabled, with `accessibilityLabel="VOX voice-activated mode is desktop-only in 52.1c"` so testers understand why it isn't tappable.
- **Auto-record via `expo-audio`.** MediaRecorder isn't part of react-native-webrtc; instead we run the existing `expo-audio` recorder alongside the WebRTC session, capturing the LOCAL mic. On `session-ended` (or panel unmount) the recorded `.m4a` uploads to `POST /api/walkie/messages` with `metadata:{source:"live_session", session_id}`, so it surfaces in the timeline with the same 24h TTL as an async clip.
- **Foreground service scope.** The `FOREGROUND_SERVICE_MICROPHONE` permission is present, but a true screen-off background live session would require a native module beyond `react-native-webrtc` — deferred to a follow-up phase. Current UX assumes users hold the phone during a live session (PTT flow), so foregrounded operation is the expected state.

**Bundle-size delta** (measured with `expo prebuild` + `pod install` on a Feb-2026 checkout):
- iOS: +~9 MB (WebRTC.framework)
- Android: +~7 MB (libwebrtc.so per ABI)
- Total dev-client size increase well under the 100 MB PAUSE gate.

**Smoke test on the rebuilt dev-client:**
1. Log in as `mike@aquaterra.com` (pool tech) on Device A, open Pool Team channel.
2. Log in as `admin@aquaterra.com` on Device B, open the same channel.
3. Device A: flip the "Live channel" toggle in the footer.
4. Device B: flip the "Live channel" toggle. Both devices should see "Live · 2 on channel".
5. Device A: hold the big "Hold to talk" button and speak — Device B hears the audio in real time.
6. Both devices: release the toggle. Within a couple seconds, a new `.m4a` clip appears in the Pool Team timeline attributed to the last-out participant.


---

## Phase 52.1d · metered.ca TURN wiring (Feb 2026)

Without TURN, live sessions work on LAN + friendly-NAT clients but **fail for users behind symmetric NAT** (about 8% of consumer connections — mostly LTE hotspots + hotel Wi-Fi). This section wires the metered.ca free tier so those clients relay through a hosted TURN pool instead of trying to connect P2P.

### One-time metered.ca signup
1. Sign up at <https://dashboard.metered.ca/> — free tier ships 50 GB / month TURN traffic, plenty for the small teams this app targets.
2. In the dashboard, open **TURN Server → Global TURN Server**.
3. Copy the credentials block. It looks like:
   ```json
   {
     "urls": [
       "turn:global.relay.metered.ca:80",
       "turn:global.relay.metered.ca:443?transport=tcp",
       "turns:global.relay.metered.ca:443"
     ],
     "username": "abcdef1234567890",
     "credential": "xyz-your-secret-here"
   }
   ```

### Backend `.env` config
Add to `/app/backend/.env` (comma-join the URLs — the backend splits on `,` at request time):

```bash
METERED_TURN_URLS=turn:global.relay.metered.ca:80,turn:global.relay.metered.ca:443?transport=tcp,turns:global.relay.metered.ca:443
METERED_TURN_USERNAME=abcdef1234567890
METERED_TURN_CREDENTIAL=xyz-your-secret-here
```

⚠️ **Never commit real credentials.** `backend/.env.example` ships placeholder-only rows for these three keys.

### Apply
```bash
sudo supervisorctl restart backend
```

### Verify
```bash
curl -s -H "Authorization: Bearer $(curl -s -X POST http://localhost:8001/api/auth/login -H 'Content-Type: application/json' -d '{"email":"admin@aquaterra.com","password":"password123"}' | jq -r .access_token)" \
  http://localhost:8001/api/walkie/ice-servers | jq
```

Expected shape (TURN active):
```json
{
  "ice_servers": [
    { "urls": "stun:stun.l.google.com:19302" },
    {
      "urls": ["turn:global.relay.metered.ca:80", "turn:global.relay.metered.ca:443?transport=tcp", "turns:global.relay.metered.ca:443"],
      "username": "abcdef1234567890",
      "credential": "xyz-your-secret-here"
    }
  ]
}
```

Missing any of the three env vars → STUN-only response + a `walkie.signaling metered.ca TURN not configured — STUN-only` log line at boot (safe fallback).

### Fallback behavior
- **STUN-only** (any TURN env var missing): every P2P audio session works on the same LAN + friendly-NAT scenarios. Symmetric-NAT clients (hotel Wi-Fi, some LTE carriers) will connection-fail after ICE gathering — the client shows a `Live unavailable` state and drops back to async clips.
- **All three set + valid**: TURN relays symmetric-NAT clients. Latency is ~50-150 ms higher than P2P (relay hop) but that's still well below the 250 ms threshold the walkie UX targets.

