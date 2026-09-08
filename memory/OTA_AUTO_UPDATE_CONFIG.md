# OTA Auto-Update Configuration

> **Last updated**: 2026-09-08 · Iteration 75

## How OTA works in this project

This Expo app uses **EAS Update** (Expo Application Services) for over-the-air JavaScript + asset updates. Field techs receive updates automatically without reinstalling from TestFlight / Google Play.

### Flow

1. **Cold start**: `expo-updates` checks `https://u.expo.dev/<projectId>` for a new bundle.
2. If a new update is available, it downloads in the background.
3. On the **next** cold start, the new bundle is applied.
4. In-app, a subtle alert offers "Restart now" — the tech can choose to apply immediately or defer.
5. The app **never** force-restarts mid-session — that would destroy in-progress offline queue state.

### Configuration

| Key | Value | File |
|-----|-------|------|
| `updates.enabled` | `true` | `app.config.js` |
| `updates.checkAutomatically` | `"ON_LOAD"` | `app.config.js` |
| `updates.fallbackToCacheTimeout` | `0` (never block UI) | `app.config.js` |
| `updates.url` | `https://u.expo.dev/bdd4bc95-5d7c-46d8-8243-0b6ed1e9aa19` | `app.config.js` |
| `runtimeVersion.policy` | `"fingerprint"` | `app.config.js` |
| Build channels | `development`, `preview`, `production` | `eas.json` |

### Runtime Version Policy: `fingerprint`

The `fingerprint` policy generates a runtime version hash from the project's native dependencies (Podfile.lock, build.gradle, etc.). This means:

- **OTA-safe changes** (JS, assets, styling) share the same fingerprint → update applies automatically.
- **Native-breaking changes** (new native modules, SDK bumps) produce a new fingerprint → OTA update is rejected, and a new binary build is required.

This is the safest policy because it prevents OTA updates from shipping to binaries with incompatible native code.

### EAS Update Channels (`eas.json`)

| Profile | Channel | Purpose |
|---------|---------|---------|
| `development` | `development` | Dev builds, internal testing |
| `preview` | `preview` | QA / TestFlight / Internal Play Store track |
| `production` | `production` | Live production builds |

### In-App Update Listener

File: `src/hooks/useOtaUpdateListener.ts`

- Checks for updates on cold start and every foreground transition (5-min cooldown).
- Fetches new bundles in the background.
- Shows a non-intrusive alert: "Update available — Restart to apply?"
- Tech can tap "Later" (update applies on next cold start) or "Restart now".
- **NEVER** auto-reloads mid-session. This is critical because:
  - Techs may have in-progress checklist edits.
  - The Phase 2 offline write queue may have pending items.
  - A mid-session reload would lose unsaved state.

---

## ⚠️ What OTA CAN and CANNOT ship

### ✅ OTA-safe (JS bundle updates)
- UI changes (new screens, components, styling)
- Business logic changes (validation, calculations)
- API endpoint changes (new routes, payload shapes)
- Asset changes (images, fonts — if bundled)
- Bug fixes in TypeScript/JavaScript code
- New or updated React components

### ❌ Requires a new binary build (TestFlight / Play Store)
- Bumping `expo` SDK version (e.g., 54 → 55)
- Adding or bumping native modules:
  - `expo-camera`, `expo-sqlite`, `expo-location`
  - `react-native-maps`, `react-native-reanimated`
  - `@stripe/stripe-react-native`
  - Any package with iOS/Android native code
- Changing `app.config.js` fields that affect native builds:
  - `ios.bundleIdentifier`, `android.package`
  - `ios.buildNumber`, `android.versionCode`
  - `plugins` array (adding/removing config plugins)
  - `ios.infoPlist` permission strings
  - `android.permissions`
- Changing the Expo Router entry point or navigation structure that requires native stack changes

### How to tell if a change is OTA-safe
Run `npx expo-updates fingerprint:generate` before and after your change. If the fingerprint changes, a new binary is required.

---

## Publishing an OTA Update

From your local machine or CI:

```bash
# Preview channel (for QA testing)
cd mobile
eas update --channel preview --message "Fix: chemistry label alignment"

# Production channel (for live users)
cd mobile
eas update --channel production --message "v1.2.1: Chemistry readings unification"
```

### CI Automation (recommended)

Add to your CI/CD pipeline (GitHub Actions, etc.):

```yaml
- name: Publish OTA update
  if: github.ref == 'refs/heads/main'
  run: |
    cd mobile
    npx eas-cli update --channel production --message "${{ github.event.head_commit.message }}"
```

---

## Rollback

If a bad OTA update goes out:

```bash
# List recent updates
eas update:list --channel production

# Roll back to a specific update group
eas update:rollback --channel production
```

Or publish a fixed update immediately — the next app cold start will pick it up.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Update not applying | App hasn't cold-started since fetch | Kill and relaunch, or tap "Restart now" in the alert |
| "No compatible update" | Runtime version mismatch | Publish a new binary with matching fingerprint |
| OTA check fails silently | CDN unreachable / dev build | Expected in dev — only works in production builds |
| Update causes crash | JS error in new bundle | Expo falls back to the previous working bundle automatically |
