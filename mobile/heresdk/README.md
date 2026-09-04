# HERE Maps SDK — manual binary drop (mobile)

> Phase K39b · Feb-2026 — until `react-native-here-explore` fully proxies HERE's native SDK via the Expo config plugin, the raw binaries have to be dropped into this folder before an Android / iOS build. **Do NOT commit the binaries.** They're licensed artifacts and each dev / CI runner has to pull their own from developer.here.com.

## Prerequisites

1. Create a HERE **project** at [platform.here.com](https://platform.here.com).
2. Inside the project, generate an **Access Key ID** + **Access Key Secret** pair. These map to the two env vars used by the app:

| Variable | Where | Notes |
| --- | --- | --- |
| `EXPO_PUBLIC_HERE_ACCESS_KEY_ID` | plain env / EAS var | Public-safe identifier — embedded in the app bundle. |
| `HERE_ACCESS_KEY_SECRET` | **EAS secret only** | Never plain env, never git. Used at build time by the config plugin to sign the SDK init request. |
| `EXPO_PUBLIC_MAPS_PROVIDER` | plain env / EAS var | `"google"` (default) \| `"here"`. |

## Drop procedure

### Android
1. Download `heresdk-explore-android-<VERSION>.aar` from developer.here.com → your project → SDK downloads → **HERE SDK for Android (Explore Edition)**.
2. Drop it here: `mobile/heresdk/android/heresdk.aar`.
3. Run `yarn expo prebuild --clean` — the config plugin registered in `app.config.js` links the `.aar` into the Android module tree via `settings.gradle`.

### iOS
1. Download `heresdk-explore-ios-<VERSION>.xcframework.zip` from the same place.
2. Unzip and drop the folder: `mobile/heresdk/ios/heresdk.xcframework/`.
3. Run `yarn expo prebuild --clean` — the config plugin adds the framework to the Podfile as a `pod 'heresdk', :path => '...'` entry.

## `postinstall` guard

`mobile/package.json` runs a tiny `postinstall` script that checks for the presence of the binaries above. If either is missing, the script prints:

```
[K39b] HERE SDK binaries not present. HERE mode will render a
       "Map unavailable" placeholder. Follow mobile/heresdk/README.md
       to enable HERE tiles in a dev-client / EAS build.
```

The script exits **0** so `yarn install` never fails — this is intentional so contributors who only touch non-map code don't have to fight with HERE creds.

## What still works without HERE creds

- Google mode (`EXPO_PUBLIC_MAPS_PROVIDER=google`, the default) — react-native-maps runs unchanged.
- HERE mode without the binaries — every map surface renders the K39b `MapUnavailablePlaceholder` (from `src/utils/mapsKey.tsx`) with the message "HERE SDK not installed. See mobile/heresdk/README.md." No crashes.

## Cutover checklist (for K39c, later)

1. Flip `EXPO_PUBLIC_MAPS_PROVIDER=here` on staging.
2. Verify tile rendering + marker interactions on dev-client + TestFlight.
3. Once green, remove the react-native-maps dependency.
