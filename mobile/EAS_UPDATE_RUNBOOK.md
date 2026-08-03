# EAS Update Runbook

Phase 28 · Feb-2026 — configuration and operator guide for
Over-The-Air JavaScript updates to the Pool & Landscaping CRM
mobile app.

This runbook covers publishing JS-only changes without a store
release. It does **not** cover full native builds — for those,
see the Expo docs or your existing build pipeline.

---

## 1 · One-time prerequisites

### 1a · Install the EAS CLI

```bash
npm install -g eas-cli
# or (in this repo — yarn is the canonical package manager):
yarn global add eas-cli
```

Confirm:

```bash
eas --version
# → eas-cli/12.x.x or newer
```

### 1b · Log in to EAS

```bash
eas login
```

Uses the same Expo account that owns the app under **expo.dev**.

### 1c · Link the project (one time)

If the project isn't linked yet, in `/app/mobile`:

```bash
eas init
```

This writes `extra.eas.projectId` into `app.json` and returns the
canonical project id (a UUID). Copy that UUID.

### 1d · Swap the `PROJECT_ID` placeholder (and flip the runtime ON)

Phase 28 shipped `app.json` with a placeholder AND with
`expo-updates` **disabled at runtime** so the app cannot 404 on
boot before EAS is provisioned:

```json
"updates": {
  "url": "https://u.expo.dev/PLACEHOLDER_EXPO_PROJECT_ID",
  "enabled": false,
  "fallbackToCacheTimeout": 0,
  "checkAutomatically": "NEVER"
}
```

**Two edits are required before your first `eas update` call:**

1. Replace the string `PLACEHOLDER_EXPO_PROJECT_ID` with the real
   project UUID (from `eas init`).
2. In the same `updates` block, flip:
   - `"enabled": false` → `"enabled": true`
   - `"checkAutomatically": "NEVER"` → `"ON_LOAD"` (or
     `"ON_ERROR_RECOVERY"` if you want update checks only after
     a JS crash).

If you skip either edit, the runtime either does not fetch
updates (`enabled: false`) or does not check on foreground
(`checkAutomatically: "NEVER"`). Both are the deliberate P0
hotfix state that keeps the app safely running against the
placeholder URL.

The validation script (`§1e`) enforces this invariant:
`enabled: false` + `checkAutomatically: "NEVER"` MUST both be
true while the placeholder is in the URL. If you flip
`enabled: true` while the placeholder is still there, the
script exits 1 with a diagnostic — that catches the exact
regression that broke Phase 28's first pass.

### 1e · Validate the config

```bash
node /app/mobile/scripts/validate_eas_update_config.mjs
```

- Exit `0` — everything ready.
- Exit `1` — human-readable diagnostics printed; fix the noted
  drift before publishing.

---

## 2 · Publish an update

### 2a · Preview branch

Preview updates are the safe staging channel — internal-distribution
builds (`eas.json → build.preview`) pick them up. Use this for
smoke-testing JS changes before promoting to production.

```bash
cd /app/mobile
eas update --branch preview --message "Phase 25b · JobTrackerTiles geometry fix"
```

The `--message` flag lands in the EAS dashboard alongside the
git commit — keep it human-readable and reference the phase.

### 2b · Production branch

After preview has been validated in Expo Go (tunnel build) or an
internal-distribution build:

```bash
eas update --branch production --message "Phase 25b promoted to prod"
```

**Never publish to production without a preview soak first.** OTA
updates land instantly on all installed clients — a bad JS bundle
can brick the field techs' devices until you republish.

### 2c · Promotion pattern (preview → production)

If you'd rather promote an existing preview update to production
without a rebuild, use republish:

```bash
# List recent updates and grab the update UUID from preview.
eas update:list --branch preview

# Republish to production.
eas update:republish --group <update-uuid> --branch production
```

This is idempotent — the same bundle bytes land on production
clients.

---

## 3 · Roll back

Rollback = republish the last-known-good update UUID:

```bash
eas update:list --branch production
# Find the last "good" update UUID above the broken one.

eas update:republish --group <good-update-uuid> --branch production \
  --message "Rollback of <broken-update-uuid> — <reason>"
```

The old bundle re-lands on every production client at their next
`checkAutomatically: ON_LOAD` cycle (i.e., on app foreground).

### 3a · Emergency: force clients to a specific commit

Rare — only if `eas update:republish` isn't enough. See
<https://docs.expo.dev/eas-update/rollbacks/> for the escape
hatches (`--republish` with `--platform`, force-branch swap, etc.).

---

## 4 · OTA-safe vs. store-release-required changes

| Change type                                                | OTA safe? | Notes |
|------------------------------------------------------------|-----------|-------|
| JS / TSX code (screens, hooks, business logic)             | ✅ Yes    | The 90% case. |
| New JS-only dep already in `package.json`                  | ✅ Yes    | Metro bundles it into the update payload. |
| Asset changes (images, fonts) referenced from JS           | ✅ Yes    | Bundled into the update. |
| CSS / styled-components tweaks                             | ✅ Yes    |  |
| Adding a new `expo-*` module with **JS-only** surface      | ⚠️ Maybe  | Check the module's README — if it links native code, no. |
| Adding a new native module (react-native-*, expo-*  native)| ❌ No     | Store rebuild required. |
| Bumping Expo SDK (54 → 55)                                 | ❌ No     | Store rebuild required. |
| Changing `runtimeVersion` policy                           | ❌ No     | Breaks client/update pairing. |
| Modifying `app.json` `plugins`                             | ❌ No     | Native config changes need rebuild. |
| Modifying `AndroidManifest.xml` / `Info.plist` entries     | ❌ No     | Store rebuild required. |
| Adding/removing permissions                                | ❌ No     | Store rebuild required. |

### The `runtimeVersion` contract

`app.json` sets:

```json
"runtimeVersion": {
  "policy": "appVersion"
}
```

Meaning: every OTA update is scoped to the app's `expo.version`
string (currently `1.0.0`). A client on `1.0.0` will only receive
updates published under `runtimeVersion=1.0.0`. When you bump
`expo.version` to `1.1.0`, you MUST also rebuild the store binary —
old `1.0.0` clients won't receive updates published against `1.1.0`.

This is the correct choice for a workforce app: it forces a native
rebuild whenever native surface changes, but keeps JS-only fixes
frictionless.

---

## 5 · What Phase 28 shipped (config summary)

| File | Change |
|------|--------|
| `/app/mobile/app.json` | Added `expo.updates.url` (placeholder), `expo.updates.fallbackToCacheTimeout: 0`, `expo.updates.checkAutomatically: "ON_LOAD"`, and `expo.runtimeVersion.policy: "appVersion"` |
| `/app/mobile/eas.json` | Created — `cli.appVersionSource: remote`, three build profiles (`development` / `preview` / `production`) with matching `channel` fields, and two `update` branches (`preview` / `production`) |
| `/app/mobile/package.json` | Added `expo-updates: ~29.0.13` (SDK 54 compatible) |
| `/app/mobile/scripts/validate_eas_update_config.mjs` | New — offline config sanity check |
| `/app/mobile/EAS_UPDATE_RUNBOOK.md` | This file |

The **only** post-shipping change needed before the first
`eas update` call is swapping `PLACEHOLDER_EXPO_PROJECT_ID` for
the real project UUID (see §1d).

---

## 6 · Troubleshooting quick reference

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `eas update` errors "Invalid project ID" | Placeholder not swapped | See §1d. |
| Update publishes but clients don't pick it up | Client `runtimeVersion` mismatch | Check `expo.version` in `app.json` matches the version the installed app was built with. If they've drifted, you need a store rebuild. |
| Preview build sees update but production build doesn't | Wrong `channel` in the store binary | The store binary must be built with `--profile production` (or `--profile preview`) so its channel matches the `eas update --branch` you published against. |
| `expo-updates` package missing on install | `yarn` cache stale | `rm -rf node_modules yarn.lock && yarn install` in `/app/mobile`. |
