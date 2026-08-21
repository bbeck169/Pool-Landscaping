# App Store Submission Handoff — Phase P11c

**Generated**: 2026-08-20
**Scope**: Items 8, 9, 10 from the Phase P10 App Store Readiness Audit
**App**: Pool Landscaping (`com.poolscape.audit`)

---

## Item 8 — App Store Connect Data Collection Questionnaire

Apple's App Store Connect requires you to declare **every category of data your app collects**, whether it's linked to the user's identity, used for tracking, or both. Below is the completed questionnaire mapped to the backend schema and mobile SDKs.

### 8.1  Data Types Collected

| # | Apple Category | Apple Sub-type | Collected? | Linked to Identity? | Used for Tracking? | Backend Collection / SDK Source | Purpose |
|---|---|---|---|---|---|---|---|
| 1 | **Location** | Precise Location | ✅ Yes | ✅ Yes | ❌ No | `db.gps_pings` (`lat`, `lon`, `accuracy_m`, `user_id`, `tenant_id`) — written by `expo-location` background task | App Functionality — shift GPS tracking for route verification |
| 2 | **Location** | Coarse Location | ❌ No | — | — | — | Not collected separately |
| 3 | **Contact Info** | Name | ✅ Yes | ✅ Yes | ❌ No | `db.users` (`first_name`, `last_name`), `db.customers` (`name`, `first_name`, `last_name`) | App Functionality — user accounts & CRM |
| 4 | **Contact Info** | Email Address | ✅ Yes | ✅ Yes | ❌ No | `db.users` (`email`), `db.customers` (`email`), `db.leads` (`email`) | App Functionality — authentication, notifications, invoicing |
| 5 | **Contact Info** | Phone Number | ✅ Yes | ✅ Yes | ❌ No | `db.users` (`phone`), `db.customers` (`phone`, `phones[]`), `db.leads` (`phone`) | App Functionality — SMS notifications, On My Way alerts |
| 6 | **Contact Info** | Physical Address | ✅ Yes | ✅ Yes | ❌ No | `db.customers` (`address`, `city`, `state`, `zip`), `db.jobs` (`address`, `location_lat`, `location_lng`) | App Functionality — service scheduling & dispatch |
| 7 | **Financial Info** | Payment Info | ✅ Yes | ✅ Yes | ❌ No | `db.stripe_charges` (`payment_intent_id`, `amount`), `db.invoices` — Stripe SDK (WebView) handles card PCI data; app never stores raw card numbers | App Functionality — invoice payments |
| 8 | **Financial Info** | Other Financial Info | ✅ Yes | ✅ Yes | ❌ No | `db.invoices` (`total`, `balance_due`), customer credits (`db.customers.credits`) | App Functionality — billing & account balance |
| 9 | **User Content** | Photos or Videos | ✅ Yes | ✅ Yes | ❌ No | `db.files` (uploaded via `expo-image-picker` camera/library), job before/after photos, service report photos | App Functionality — job documentation |
| 10 | **User Content** | Audio Data | ✅ Yes | ✅ Yes | ❌ No | `react-native-webrtc` walkie-talkie streams — real-time only, not persisted to disk | App Functionality — team walkie-talkie communication |
| 11 | **User Content** | Other User Content | ✅ Yes | ✅ Yes | ❌ No | Job notes, customer notes, template field entries, lead notes (`db.jobs.notes`, `db.leads.notes`) | App Functionality — service records |
| 12 | **Identifiers** | User ID | ✅ Yes | ✅ Yes | ❌ No | `db.users` (`id`), `db.gps_pings` (`user_id`) | App Functionality — authentication & data association |
| 13 | **Identifiers** | Device ID | ❌ No | — | — | — | No device ID collected or stored |
| 14 | **Usage Data** | Product Interaction | ✅ Yes | ✅ Yes | ❌ No | Server-side request logs (route hits, timestamps) — no client-side analytics SDK | App Functionality — service monitoring |
| 15 | **Diagnostics** | Crash Data | ❌ No | — | — | — | No crash reporting SDK (Sentry/Crashlytics) integrated |
| 16 | **Diagnostics** | Performance Data | ❌ No | — | — | — | No performance monitoring SDK integrated |
| 17 | **Health & Fitness** | — | ❌ No | — | — | — | Not collected |
| 18 | **Sensitive Info** | — | ❌ No | — | — | — | Not collected |
| 19 | **Browsing History** | — | ❌ No | — | — | — | Not collected |
| 20 | **Search History** | — | ❌ No | — | — | — | Not collected |
| 21 | **Contacts** | — | ❌ No | — | — | — | No address book access |
| 22 | **Purchases** | Purchase History | ✅ Yes | ✅ Yes | ❌ No | `db.invoices`, `db.stripe_charges` — service transaction history | App Functionality — invoice records |

### 8.2  Copy-Paste Answers for App Store Connect

When filling out the **App Privacy** section in App Store Connect, select these:

**Data Used to Track You:** None
**Data Linked to You:**
- Precise Location
- Name, Email Address, Phone Number, Physical Address
- Payment Info, Other Financial Info
- Photos or Videos, Audio Data, Other User Content
- User ID
- Product Interaction
- Purchase History

**Data Not Linked to You:** None (all collected data is linked to authenticated user accounts)

### 8.3  Privacy Nutrition Label Summary

```
┌─────────────────────────────────────────────┐
│  Data Used to Track You         NONE        │
├─────────────────────────────────────────────┤
│  Data Linked to You                         │
│  ├─ Location (Precise)                      │
│  ├─ Contact Info (Name, Email, Phone, Addr) │
│  ├─ Financial Info (Payments, Balances)      │
│  ├─ User Content (Photos, Audio, Notes)      │
│  ├─ Identifiers (User ID)                   │
│  ├─ Usage Data (Product Interaction)         │
│  └─ Purchases (History)                     │
├─────────────────────────────────────────────┤
│  Data Not Linked to You         NONE        │
└─────────────────────────────────────────────┘
```

### 8.4  Key Notes for Reviewer

- **No advertising SDKs**: The app contains zero ad-tech, attribution, or analytics SDKs. No data is shared with third-party advertisers.
- **No tracking**: The app does not track users across other companies' apps or websites.
- **Stripe PCI compliance**: Credit card numbers are handled entirely by Stripe's WebView SDK. The app backend stores only Stripe payment intent IDs and amounts — never raw card data.
- **GPS data retention**: `db.gps_pings` has a server-side daily purge job (`gps_pings_retention_purge`) that runs at 04:00 UTC. Data is retained only for the configured tenant retention window.
- **Audio streams**: Walkie-talkie audio is real-time WebRTC peer-to-peer. Audio is not recorded or stored on any server.

---

## Item 9 — Mapbox Token Wiring

### 9.1  Token Types

Mapbox requires **two** token types for React Native (`@rnmapbox/maps`):

| Token Type | Prefix | Scope | Where Used | Security |
|---|---|---|---|---|
| **Public Access Token** | `pk.` | Read-only map tiles, geocoding, directions | Runtime — embedded in JS bundle via `EXPO_PUBLIC_MAPBOX_TOKEN` env var | Safe to ship in client builds. Restrict to your bundle ID in Mapbox Dashboard → Token Scopes. |
| **Secret Download Token** | `sk.` | `DOWNLOADS:READ` — fetches the Mapbox native SDK binary at build time | Build-time only — referenced in `RNMAPBOX_MAPS_DOWNLOAD_TOKEN` env var, interpolated into `app.json` plugin config | **NEVER** ship in client bundle. Used only by EAS Build / `pod install`. Store in EAS Secrets or CI env vars. |

### 9.2  Environment Variable Wiring

```
# .env (local development)
EXPO_PUBLIC_MAPBOX_TOKEN=pk.eyJ1Ijo...    # Public — loaded at runtime via process.env
RNMAPBOX_MAPS_DOWNLOAD_TOKEN=sk.eyJ1Ijo...  # Secret — build-time only

# EAS Secrets (production builds)
eas secret:create --name EXPO_PUBLIC_MAPBOX_TOKEN --value "pk.eyJ1Ijo..."
eas secret:create --name RNMAPBOX_MAPS_DOWNLOAD_TOKEN --value "sk.eyJ1Ijo..."
```

### 9.3  `app.json` Plugin Config (already wired)

```json
{
  "plugins": [
    ["@rnmapbox/maps", {
      "RNMapboxMapsDownloadToken": "$RNMAPBOX_MAPS_DOWNLOAD_TOKEN"
    }]
  ]
}
```

The `$`-interpolation means EAS Build reads the env var at build time. The `sk.` token never enters the JS bundle.

### 9.4  `__DEV__` Startup Guard

A development-mode guard has been added to `/app/mobile/app/_layout.tsx` (the root layout). It runs inside a `useEffect` on mount:

```typescript
// Phase P11c — Mapbox token placeholder guard (__DEV__ only)
useEffect(() => {
  if (!__DEV__) return;
  const token = process.env.EXPO_PUBLIC_MAPBOX_TOKEN ?? '';
  if (!token || token.startsWith('pk.REPLACE_ME')) {
    console.warn(
      '[Mapbox] ⚠️  EXPO_PUBLIC_MAPBOX_TOKEN is a placeholder ("pk.REPLACE_ME") or missing.\n' +
      'Map screens will fail. Get a free public token from:\n' +
      'https://account.mapbox.com/access-tokens/'
    );
  }
}, []);
```

**Behavior:**
- **Development** (`__DEV__ === true`): Logs a yellow console warning if the token is missing or starts with `pk.REPLACE_ME`.
- **Production** (`__DEV__ === false`): The guard early-returns. No warning, no console output, no UI banner.

### 9.5  Mapbox Dashboard Security Checklist

Before submitting to the App Store:

- [ ] Create a **new** public token in [Mapbox Dashboard](https://account.mapbox.com/access-tokens/) with only these scopes:
  - `styles:tiles` — load map tiles
  - `styles:read` — read style definitions
  - `fonts:read` — load map label fonts
  - `datasets:read` — (if using datasets)
- [ ] Restrict the token to your iOS bundle identifier: `com.poolscape.audit`
- [ ] Restrict the token to your Android package name (if applicable)
- [ ] Store the secret `sk.` download token in **EAS Secrets** only — never commit to git
- [ ] Verify `.env` is in `.gitignore` (it should be — Expo starter template includes this)
- [ ] Remove or rotate any tokens that were committed to version control

### 9.6  `.env.example` Updated

`/app/mobile/.env.example` has been updated with annotated Mapbox entries:

```
# Mapbox — Public access token (pk.*). Loaded at runtime for map rendering.
# Get one free at https://account.mapbox.com/access-tokens/
# Restrict scopes: styles:tiles, styles:read, fonts:read
# Restrict to bundle ID: com.poolscape.audit
EXPO_PUBLIC_MAPBOX_TOKEN=pk.REPLACE_ME

# Mapbox — Secret download token (sk.*). Build-time ONLY.
# Required scope: DOWNLOADS:READ
# Used by @rnmapbox/maps plugin to fetch native SDK during `eas build`.
# NEVER ship in client bundle. Store in EAS Secrets for CI.
RNMAPBOX_MAPS_DOWNLOAD_TOKEN=sk.REPLACE_ME
```

---

## Item 10 — App Store Screenshots

### 10.1  Required Screenshot Sizes

Apple requires screenshots for each device size your app supports. Since `supportsTablet: true` is set, iPad screenshots are also required.

| Device Class | Display Size | Resolution (px) | Orientation | Required? |
|---|---|---|---|---|
| iPhone 6.7" | iPhone 16 Pro Max / 15 Pro Max | 1290 × 2796 | Portrait | ✅ Yes (primary) |
| iPhone 6.5" | iPhone 14 Plus / 11 Pro Max | 1284 × 2778 | Portrait | ✅ Yes |
| iPhone 6.1" | iPhone 16 / 15 / 14 | 1179 × 2556 | Portrait | Optional (auto-scaled from 6.7") |
| iPhone 5.5" | iPhone 8 Plus / SE (3rd gen) | 1242 × 2208 | Portrait | ✅ Yes (still required for older devices) |
| iPad 12.9" (6th gen) | iPad Pro 12.9" | 2048 × 2732 | Portrait | ✅ Yes (if `supportsTablet: true`) |
| iPad 13" (M4) | iPad Pro 13" | 2064 × 2752 | Portrait | ✅ Yes (new requirement 2025+) |
| iPad 11" | iPad Pro 11" / iPad Air | 1668 × 2388 | Portrait | Optional (auto-scaled from 12.9") |

**Minimum**: 2 screenshots per size. **Maximum**: 10 per size. **Recommended**: 5–8 per size.

### 10.2  Recommended 5 Screens & Marketing Captions

Based on the app's strongest features and typical App Store conversion patterns:

| # | Screen | Route | Caption (≤30 chars for subtitle) | Marketing Copy (≤170 chars for description) | Why This Screen |
|---|---|---|---|---|---|
| 1 | **Today's Schedule** | `/(app)/schedule/calendar` (Grid view with jobs) | "Your Day, Organized" | "See every job, route, and time slot at a glance. Tap to navigate, swipe to reschedule. Built for field teams." | First impression — shows the core value prop for technicians |
| 2 | **Live Dispatch Map** | `/(app)/dispatch` | "Track Your Crew Live" | "Real-time GPS tracking on an interactive map. Know where every technician is during active shifts." | Differentiator — GPS tracking is a premium feature |
| 3 | **Job Detail with Photos** | `/job/[id]` (with before/after photos visible) | "Document Every Job" | "Before & after photos, service checklists, water chemistry readings, and customer notes — all in one place." | Shows depth of job management |
| 4 | **Customer Portal Home** | `/portal/home` (customer view) | "Your Pool, Your Portal" | "Customers see service history, pay invoices, request visits, and refer friends — right from their phone." | Demonstrates the B2B2C value |
| 5 | **Invoice & Payment** | `/invoice/[id]` (with Stripe payment) | "Get Paid Faster" | "Send professional invoices with one-tap Stripe payments. Promo codes, credits, and card-on-file supported." | Revenue feature — appeals to business owners |

**Alternate / Bonus screens** (if submitting 8–10 per size):

| # | Screen | Caption |
|---|---|---|
| 6 | Time Clock (`/time-clock`) | "Clock In, Track Hours" |
| 7 | AI Dock / AI Employee chat | "AI That Works For You" |
| 8 | Marketing Broadcasts | "Reach Every Customer" |

### 10.3  Screenshot Capture Methods

#### Method A: Xcode Simulator (Recommended for Store Quality)

```bash
# 1. Build for simulator
eas build --platform ios --profile preview

# 2. Open in Simulator (select each required device)
#    - iPhone 16 Pro Max (6.7")
#    - iPhone 14 Plus (6.5")
#    - iPhone 8 Plus (5.5")
#    - iPad Pro 12.9" (6th gen)
#    - iPad Pro 13" (M4)

# 3. Navigate to each screen, then:
#    Cmd+S in Simulator → saves PNG to Desktop
#    OR: xcrun simctl io booted screenshot ~/Desktop/screenshot.png

# 4. Screenshots are pixel-perfect at the correct resolution
```

#### Method B: Expo Dev Client on Physical Device

```bash
# 1. Install dev client on device
eas build --platform ios --profile development

# 2. Navigate to each screen
# 3. Take native iOS screenshot (Side button + Volume Up)
# 4. Screenshots match device's native resolution
```

#### Method C: Programmatic Capture (for CI/automation)

```typescript
import { captureRef } from 'react-native-view-shot';
import * as FileSystem from 'expo-file-system';

// Wrap target screen in a ref
const screenRef = useRef<View>(null);

const captureScreen = async () => {
  const uri = await captureRef(screenRef, {
    format: 'png',
    quality: 1.0,
    // Let it capture at native resolution
  });
  // Copy to a known location
  await FileSystem.copyAsync({
    from: uri,
    to: `${FileSystem.documentDirectory}screenshot_${Date.now()}.png`,
  });
};
```

> **Note**: Install `react-native-view-shot` first: `yarn add react-native-view-shot`

#### Method D: Fastlane (Full Automation)

```ruby
# Fastfile
lane :screenshots do
  capture_screenshots(
    scheme: "PoolLandscaping",
    devices: [
      "iPhone 16 Pro Max",
      "iPhone 14 Plus",
      "iPhone 8 Plus",
      "iPad Pro (12.9-inch) (6th generation)"
    ],
    languages: ["en-US"],
    output_directory: "./store-assets/screenshots"
  )
  frame_screenshots(
    path: "./store-assets/screenshots"
  )
end
```

### 10.4  Screenshot Design Tips

- **Add device frames**: Use [Screenshots Pro](https://screenshots.pro) or Figma templates to add iPhone/iPad frames around raw screenshots.
- **Add marketing text**: Overlay the captions from §10.2 above each screenshot. Use your brand font (Plus Jakarta Sans) at 48–64pt.
- **Consistent background**: Use a solid color or subtle gradient matching your brand. Avoid pure white — it blends with the App Store page.
- **Show real data**: Use the demo accounts (`manager@aquaterra.com`, `customer@aquaterra.com`) to populate screens with realistic-looking data before capturing.
- **Localization**: For English-only launch, one set of screenshots is sufficient. Add localized sets later if expanding to other markets.

### 10.5  Screenshot File Organization

```
/store-assets/
├── screenshots/
│   ├── iphone-6.7/
│   │   ├── 01-schedule.png
│   │   ├── 02-dispatch-map.png
│   │   ├── 03-job-detail.png
│   │   ├── 04-portal-home.png
│   │   └── 05-invoice.png
│   ├── iphone-6.5/
│   │   └── ... (same 5 screens)
│   ├── iphone-5.5/
│   │   └── ... (same 5 screens)
│   ├── ipad-12.9/
│   │   └── ... (same 5 screens)
│   └── ipad-13/
│       └── ... (same 5 screens)
└── marketing/
    ├── app-icon-1024.png
    ├── feature-graphic.png
    └── promo-text.md
```

---

## Appendix A — Quick Reference: What to Paste Where

| App Store Connect Field | Value |
|---|---|
| **Privacy Policy URL** | `https://<your-domain>/privacy` (must be created — see Phase P11b) |
| **Support URL** | `https://<your-domain>/support` |
| **Category** | Business (primary), Productivity (secondary) |
| **Age Rating** | 4+ (no objectionable content; photos are service documentation only) |
| **Copyright** | `© 2026 Aquaterra Pool & Landscape` |
| **Bundle ID** | `com.poolscape.audit` |
| **SKU** | `poolscape-audit-ios-001` |
| **Price** | Free (revenue is via physical service payments, not in-app purchases) |
| **Encryption** | Uses Exempt Encryption (HTTPS/TLS only) — `usesNonExemptEncryption: false` already set in `app.json` |
| **IDFA** | Not used — no advertising SDK |
| **Sign in with Apple** | Not required — app uses email/password only, no third-party social login |

## Appendix B — Pre-Submission Checklist

- [ ] All 10 P10 audit items resolved (Items 1-7 in P11a, Items 8-10 in this doc)
- [ ] Account deletion flow implemented (Phase P11b — deferred)
- [ ] Privacy policy URL live and accessible
- [ ] Mapbox public token scoped to bundle ID
- [ ] Mapbox secret token in EAS Secrets (not in git)
- [ ] Screenshots captured for all required device sizes
- [ ] `eas build --platform ios --profile production` succeeds
- [ ] `eas submit --platform ios` configured with Apple credentials
- [ ] App Store Connect metadata filled (description, keywords, screenshots, privacy)
- [ ] TestFlight internal testing completed
- [ ] Demo account credentials ready for Apple reviewer (if login required)

---

*Generated by E1-Mobile agent — Phase P11c App Store Handoff Docs.*
