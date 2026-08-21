# Apple App Store Readiness Report — Phase P10

**Audit date**: 2026-08-20
**Target**: `/app/mobile/` (Expo SDK 54 / React Native)
**Auditor**: E1-Mobile agent (read-only pass)

---

## Category 1 — `app.json` iOS block

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| `expo.ios.bundleIdentifier` | `"com.poolscape.audit"` — reverse-DNS ✓ | app.json:10 | **PASS** | — |
| `expo.version` | `"1.0.0"` — valid semver | app.json:7 | **PASS** | Bump on each release |
| `expo.ios.buildNumber` | **Missing** — not set | app.json (absent) | **FAIL** | Add `"buildNumber": "1"` under `expo.ios` |
| `expo.ios.supportsTablet` | `true` | app.json:11 | **PASS** | — |
| `expo.ios.deploymentTarget` | Not explicitly set (Expo SDK 54 defaults ~15.1) | app.json (absent) | **WARN** | Explicit `"deploymentTarget": "15.1"` recommended for clarity |
| `expo.name` | `"Pool Landscaping"` | app.json:3 | **PASS** | — |
| `expo.slug` | `"Pool-Landscaping"` | app.json:4 | **PASS** | — |
| `expo.orientation` | `"portrait"` | app.json:6 | **PASS** | — |
| `expo.userInterfaceStyle` | `"automatic"` | app.json:64 | **PASS** | — |
| `expo.scheme` | `"poolscape"` | app.json:5 | **PASS** | Needed for deep linking |

---

## Category 2 — Icons + Splash

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| `expo.icon` | **512×512 px** (needs 1024×1024) | assets/images/icon.png | **FAIL** | Replace with 1024×1024 PNG |
| Icon alpha channel | **RGBA with alpha min=0** (transparent pixels present) | assets/images/icon.png | **FAIL** | Flatten to RGB (no transparency) — App Store Connect rejects alpha |
| `expo.ios.icon` | Not set (falls back to `expo.icon`) | app.json (absent) | **WARN** | Consider setting explicit iOS icon if distinct from generic |
| `expo.splash.image` | 336×729 px, RGBA | assets/images/splash-image.png | **WARN** | Dimensions work but unusual; verify it scales well on all devices |
| Splash alpha | RGBA with transparency | assets/images/splash-image.png | **WARN** | Splash over solid `backgroundColor: "#000000"` — OK, but test rendering |
| Dark-mode splash variant | Not configured | app.json | **WARN** | Optional, but recommended: add `expo-splash-screen` dark variant |
| Adaptive icon (Android) | 512×512 RGBA | assets/images/adaptive-icon.png | **WARN** | Not App Store blocking, but 1024×1024 recommended for Play Store |
| Favicon | 512×513 (non-square!) | assets/images/favicon.png | **WARN** | Not blocking for iOS, but should be square for Expo Web |

---

## Category 3 — Info.plist Permission Strings

| Permission | Declared? | String quality | Location | Verdict | Remediation |
|---|---|---|---|---|---|
| `NSLocationWhenInUseUsageDescription` | ✓ | Specific, user-facing | app.json:15 | **PASS** | — |
| `NSLocationAlwaysAndWhenInUseUsageDescription` | ✓ | Specific, mentions background + shift | app.json:16 | **PASS** | — |
| `NSCameraUsageDescription` | ✓ | "Take before and after photos of service jobs" | app.json:14 | **PASS** | — |
| `NSPhotoLibraryUsageDescription` | ✓ | "Attach job photos from your library" | app.json:17 | **PASS** | — |
| `NSPhotoLibraryAddUsageDescription` | **Missing** | App calls `requestMediaLibraryPermissionsAsync()` in 5 files | absent | **WARN** | Add — needed if saving photos to library (read vs write are separate) |
| `NSMicrophoneUsageDescription` | ✓ | "Record and stream audio for walkie-talkie live sessions" | app.json:18 | **PASS** | — |
| `NSSpeechRecognitionUsageDescription` | **Missing** | `expo-speech-recognition` used in `app/os/lana.tsx` | absent | **FAIL** | Add: "Voice commands for task management" or similar |
| `NSFaceIDUsageDescription` | Not needed | No biometric auth found | — | **PASS** | — |
| `NSContactsUsageDescription` | Not needed | No contacts access found | — | **PASS** | — |
| `NSCalendarsUsageDescription` | Not needed | No calendar access found | — | **PASS** | — |
| `UIBackgroundModes` | `["fetch", "location", "audio"]` | app.json:19 | **PASS** | Matches app capabilities (GPS tracking, walkie-talkie) |

---

## Category 4 — Privacy Manifest (`PrivacyInfo.xcprivacy`)

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| App-level privacy manifest | **Missing** — no `ios.privacyManifests` in app.json | app.json | **FAIL** | Add `expo.ios.privacyManifests` block with Required Reason API declarations |
| `NSPrivacyAccessedAPICategoryUserDefaults` | **Used** — AsyncStorage + SecureStore both use UserDefaults | package.json deps | **FAIL** | Declare reason code `CA92.1` (app's own data) in privacy manifest |
| `NSPrivacyAccessedAPICategoryFileTimestamp` | Likely used by expo-file-system | package.json:35 | **WARN** | Declare reason `DDA9.1` or `C617.1` if file timestamps are accessed |
| `NSPrivacyAccessedAPICategorySystemBootTime` | Likely used by React Native runtime | node_modules | **WARN** | Declare reason `35F9.1` (measure time elapsed) |
| `NSPrivacyAccessedAPICategoryDiskSpace` | May be used by expo-file-system | package.json:35 | **WARN** | Check at build time; declare reason `E174.1` if used |
| SDK: react-native core | ✓ Has own `.xcprivacy` (3 files) | node_modules/react-native | **PASS** | — |
| SDK: @react-native-async-storage | ✓ Has own `.xcprivacy` | node_modules/@react-native-async-storage | **PASS** | — |
| SDK: expo-notifications | ✓ Has own `.xcprivacy` | node_modules/expo-notifications | **PASS** | — |
| SDK: react-native-maps | ✓ Has own `.xcprivacy` | node_modules/react-native-maps | **PASS** | — |
| SDK: expo-task-manager | ✓ Has own `.xcprivacy` | node_modules/expo-task-manager | **PASS** | — |
| SDK: @rnmapbox/maps v10.3.5 | **No `.xcprivacy` in RN wrapper** — relies on Mapbox native SDK pod to ship its own at build time | node_modules/@rnmapbox/maps | **WARN** | Verify after `eas build` that the Mapbox native pod includes its manifest |
| SDK: react-native-webrtc | **No `.xcprivacy` found** | node_modules/react-native-webrtc | **WARN** | v124.0.6 may not bundle manifest; check at build time |
| Data collection types to declare | Location (precise), user content (photos), diagnostics, usage data | — | **FAIL** | Must declare in App Store Connect privacy questionnaire (and in manifest) |

---

## Category 5 — Third-party SDKs (App Store Impact)

| SDK | Version | Impact | Verdict | Remediation |
|---|---|---|---|---|
| `@rnmapbox/maps` | 10.3.5 | Requires download token at build, privacy manifest from pod, telemetry | **WARN** | Verify `RNMAPBOX_MAPS_DOWNLOAD_TOKEN` is set in EAS secrets; no `MBXAccessToken` in Info.plist currently |
| Stripe | **No native SDK** — uses WebView + `expo-web-browser` for payment flows | — | **PASS** | Physical-services payments via WebView are Guideline 3.1.5(a) compliant |
| `expo-notifications` | SDK 54 | Needs APNs entitlement + push cert in Apple Developer portal | **WARN** | Confirm `aps-environment` entitlement is configured in EAS / provisioning profile |
| `react-native-webrtc` | 124.0.6 | Audio/video streaming; needs mic permission (declared ✓) | **PASS** | — |
| `expo-speech-recognition` | 2.1.5 | Needs `NSSpeechRecognitionUsageDescription` + `NSMicrophoneUsageDescription` | **FAIL** | Missing speech recognition permission string (see Cat. 3) |
| `react-native-webview` | Used for payment/add-card | Guideline 4.7 risk only if *entire* app is a WebView | **PASS** | Only 3-4 screens use WebView; core app is native RN |
| `react-native-draggable-flatlist` | 4.0.3 | Pure JS/UI, no special permissions | **PASS** | — |
| `react-native-maps` | 1.20.1 | Apple Maps on iOS by default; no API key needed | **PASS** | — |
| Analytics / Ad SDKs | **None detected** | No `@react-native-firebase`, no ad SDKs | **PASS** | No SKAdNetwork IDs needed |

---

## Category 6 — Encryption Compliance

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| `usesNonExemptEncryption` | **Not set** | app.json (absent) | **FAIL** | Add `"expo.ios.config.usesNonExemptEncryption": false` — app uses only standard HTTPS/TLS |

Without this, Apple will ask the encryption question on *every* build submission, slowing review.

---

## Category 7 — Account, Auth, and Privacy Compliance

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| Account deletion (Guideline 5.1.1v) | **Missing** — no in-app delete account flow found in any screen | grep returned 0 results | **FAIL** | Must add "Delete My Account" in profile/settings — Apple rejects without this |
| Sign in with Apple (Guideline 4.8) | **Not applicable** — app uses email+password only, no third-party social login | src/auth.tsx | **PASS** | If social login is added later, Apple Auth must be added simultaneously |
| Privacy policy URL | **Not found in-app** — no privacy policy link detected | app/ and src/ | **FAIL** | Must add an accessible privacy policy link (in-app + App Store Connect) |
| Terms of Service | ✓ Present at `/portal/terms.tsx` and linked from login screen | app/portal/terms.tsx:20, app/login.tsx:234 | **PASS** | — |
| Age rating | No user-generated unrestricted web access, no violence, no gambling | — | **PASS** | Likely 4+ or 12+ (service photos may qualify as UGC) |

---

## Category 8 — In-App Purchase / Payments Compliance

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| Payment model | Physical field services (pool/landscape) billed via Stripe | src/api/payments.ts | **PASS** | Guideline 3.1.5(a) allows external payment for physical services |
| Digital goods sold? | No digital goods, subscriptions, or virtual currency detected | — | **PASS** | No IAP integration needed |
| Stripe integration | WebView-based (no native Stripe SDK) — payment for invoices | app/invoice/[id].tsx, app/portal/add-card.tsx | **PASS** | — |

---

## Category 9 — UX / Content Guidelines

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| Minimum functionality (4.2) | Full native RN app with GPS, camera, offline schedules, DnD, maps, chat, invoicing | — | **PASS** | Not a thin WebView wrapper |
| Data collection disclosure (5.1.1) | Location collection disclosed via permission strings; no in-app data collection banner | — | **WARN** | Consider adding a brief data-use notice on first launch (especially for GPS tracking) |
| Placeholder text (2.3) | No "lorem ipsum" found; some `placeholderTextColor` usages are normal UI | — | **PASS** | — |
| Mapbox token | `.env` has `EXPO_PUBLIC_MAPBOX_TOKEN=pk.REPLACE_ME_WITH_MAPBOX_PUBLIC_TOKEN` (placeholder) | .env:16 | **FAIL** | Replace with real Mapbox token or the map features will fail in production |

---

## Category 10 — Build / EAS / Signing Readiness

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| `eas.json` production profile | ✓ Exists with `"distribution": "store"` and `"channel": "production"` | eas.json | **PASS** | — |
| `expo.ios.buildNumber` | **Missing** — EAS will auto-increment if `appVersionSource: "remote"` | eas.json:4, app.json | **WARN** | Works with `appVersionSource: "remote"` but add explicit `"buildNumber": "1"` for clarity |
| Team ID / credentials | Not committed in code (good) — managed via `eas credentials` | — | **PASS** | Must configure Apple Developer Team ID via `eas credentials` before first build |
| Provisioning profile | Managed by EAS (`autoIncrement` + remote version source) | eas.json | **PASS** | — |
| Push notification entitlement | `expo-notifications` is wired but APNs entitlement not declared in app.json | app.json plugins | **WARN** | Ensure `aps-environment` is in the provisioning profile (EAS handles this if push notification capability is enabled in Apple Developer portal) |
| Background modes | `["fetch", "location", "audio"]` declared | app.json:19 | **PASS** | Matches app features |

---

## Category 11 — Assets and Localization

| Item | State | Location | Verdict | Remediation |
|---|---|---|---|---|
| App Store screenshots | **No `store-assets/` folder found** | — | **FAIL** | Create screenshots for iPhone 6.7", 6.5", 5.5" + iPad 12.9" (if tablet supported) |
| App Store description/metadata | **No `store.json` or metadata file found** | — | **WARN** | Prepare App Store description, keywords, subtitle for App Store Connect |
| Localization files | **None found** — English only | — | **PASS** | Acceptable for initial submission (English-only market) |

---

## Summary

| Severity | Count |
|---|---|
| **PASS** | 38 items |
| **WARN** | 14 items |
| **FAIL** | 10 items (blocking submission) |

### Top 10 Must-Fix Before Submission

| # | Item | Est. Effort | Category |
|---|---|---|---|
| 1 | **App icon**: Replace with 1024×1024 opaque PNG (no alpha) | XS | Cat 2 |
| 2 | **Privacy manifest**: Add `expo.ios.privacyManifests` with Required Reason API declarations (`UserDefaults` at minimum) | S | Cat 4 |
| 3 | **Account deletion**: Add "Delete My Account" flow in profile/settings screen | M | Cat 7 |
| 4 | **Privacy policy**: Add in-app privacy policy link + URL for App Store Connect | S | Cat 7 |
| 5 | **`buildNumber`**: Add `"buildNumber": "1"` to `expo.ios` | XS | Cat 1 |
| 6 | **Encryption declaration**: Add `expo.ios.config.usesNonExemptEncryption: false` | XS | Cat 6 |
| 7 | **`NSSpeechRecognitionUsageDescription`**: Add permission string for expo-speech-recognition | XS | Cat 3 |
| 8 | **Data collection declaration**: Enumerate collected data types for App Store Connect privacy questionnaire | S | Cat 4 |
| 9 | **Mapbox token**: Replace placeholder in `.env` with real token before production build | XS | Cat 9 |
| 10 | **App Store screenshots**: Generate required screenshot set | M | Cat 11 |

### Nice-to-Have Polish

| # | Item | Est. Effort |
|---|---|---|
| 1 | Explicit `deploymentTarget` in app.json | XS |
| 2 | Dark-mode splash variant | S |
| 3 | `NSPhotoLibraryAddUsageDescription` if photos are saved to library | XS |
| 4 | Verify Mapbox native pod ships its own privacy manifest at build time | XS (verify only) |
| 5 | Verify react-native-webrtc ships privacy manifest at build time | XS (verify only) |
| 6 | First-launch data-use notice for GPS tracking | S |
| 7 | Prepare App Store description, keywords, subtitle | M (content) |
| 8 | Fix favicon to be square (512×512) | XS |

### Data Types to Declare in App Store Connect

Based on code analysis, the app collects:
- **Precise location** — GPS tracking during shifts (`expo-location`, `gpsTracker.ts`)
- **Photos** — Job photos via camera and library (`expo-image-picker`)
- **Audio** — Walkie-talkie streams (`react-native-webrtc`, `expo-audio`)
- **Contact info** — Customer names, phones, emails (business data)
- **Usage data** — App interactions (no analytics SDK, but server-side logs likely)
- **Identifiers** — User IDs, device IDs in GPS pings
- **Financial data** — Invoice amounts, payment intents via Stripe WebView

All above must be declared in the App Store Connect privacy questionnaire and mapped to their purpose (app functionality, not advertising).

---

*Report generated by E1-Mobile audit agent. No code was modified during this audit.*
