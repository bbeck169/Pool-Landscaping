# Mobile-Native Enablement (Phase 15C — partial)

## Status snapshot

The `/app/mobile/` Expo project already ships with the code for every native
feature listed in the Phase 15C brief. Nothing has been rewritten — the
enablement work needed is (a) confirming permissions in `app.config.ts`,
(b) obtaining an `EXPO_PUSH_ACCESS_TOKEN`, and (c) building a **dev client**
(the Expo Go preview cannot run background tasks or real push).

| Feature                             | Source ships? | Server hook       | Status                       |
| ----------------------------------- | ------------- | ----------------- | ---------------------------- |
| Background geofence auto-timers     | `src/geofence.ts` + `expo-task-manager` | jobs status endpoints | Needs dev-build validation on-device |
| Native camera + EXIF GPS/timestamp  | `PhotoCarousel.tsx` (`expo-image-picker`) | photo POST endpoints | Needs manifest permission + dev-build test |
| Native react-native-maps + clustering | `MapCanvas.native.tsx` | D2D lat/lng endpoints | Needs iOS/Android dev-build to confirm |
| Push notifications (Expo)           | Not yet in Expo project | `POST /api/mobile-tokens` (**new**) + `send_push_to_user` (**new**) | Server ready; needs `EXPO_PUSH_ACCESS_TOKEN` |

## Backend additions shipped in this phase

- `POST /api/mobile-tokens` — register a device token (`{token, platform, device_name}`).
- `DELETE /api/mobile-tokens?token=…` — unregister on sign-out.
- `GET /api/mobile-tokens/mine` — list this user's registered devices.
- `send_push_to_user(user_id, title, body, data)` helper — invoked automatically from `utils._push_notification` for every in-app notification. Returns `{"pushed": False, "reason": "expo-token-not-configured"}` when the env var isn't set — the whole app remains functional without push.

## To run on a real device

1. Get an Expo push access token from https://expo.dev/accounts/[account]/settings/access-tokens and add it to `/app/backend/.env`:
   ```
   EXPO_PUSH_ACCESS_TOKEN=<token>
   ```
2. Restart backend: `sudo supervisorctl restart backend`.
3. In `/app/mobile/`, install expo-notifications if not present:
   ```
   yarn add expo-notifications expo-device
   ```
4. Ensure `app.config.ts` declares:
   - `notification.icon` + `notification.color`
   - iOS: `ios.infoPlist.NSLocationAlwaysAndWhenInUseUsageDescription` + `UIBackgroundModes: ["location", "fetch"]`
   - Android: `android.permissions: ["ACCESS_BACKGROUND_LOCATION", "ACCESS_FINE_LOCATION", "FOREGROUND_SERVICE_LOCATION"]`
5. `eas build --profile development --platform ios` (or `--platform android`). Install the resulting .ipa/.apk on a physical device.
6. On sign-in, the mobile app should call `POST /api/mobile-tokens` with the Expo push token. See `mobile/src/hooks/useNotifications.ts` — wire in if not already.

## Testing checklist for the user (**HUMAN_REQUIRED**)

- [ ] Background geofence: assign a job, drive into a 100m radius of the job address, confirm the timer starts and pushes a "Auto clock-in" notification to the tech's phone.
- [ ] EXIF: capture a photo at the job site; verify the field-report entry now includes GPS lat/lng + timestamp.
- [ ] Map clustering: on the canvassing view, drop 60+ pins and confirm cluster bubbles show at zoom-out.
- [ ] Push: from a second device or the web app, mark a job as assigned → the assigned tech's phone rings with a push.
- [ ] Push falls back gracefully with `EXPO_PUSH_ACCESS_TOKEN` unset (WS-only, no crash).

## What's still deferred (needs another cycle)

- **Cluster tuning threshold** — 50-pin threshold in the brief needs to be verified against the actual `MapCanvas.native.tsx` implementation.
- **Full parity sweep** for the 8 partial + 3 deferred items in `/app/memory/parity-audit.md`. That audit still lists jobs done through Phase 14. A follow-up pass will re-audit against the Phase 15 additions and update parity totals.
- **iOS/Android permission-prompt UX polish** — the source already prompts; we haven't reviewed the copy for consistency.

## Cross-tab impersonation sync (Phase 15C sub-item)

Added: `bus.broadcast(admin["id"], {"type": "impersonation_change", ...})` on the impersonation start/end endpoints is the recommended add. It's not wired yet — the current banner uses `localStorage` + `storage` events which already syncs across tabs. If you want an actual push (for cross-device sync too), wire it into `routers/portal_admin.py` where impersonation is minted/ended.
