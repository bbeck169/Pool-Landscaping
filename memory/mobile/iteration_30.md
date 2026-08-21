# Iteration 30 — Phase P11c: App Store Handoff Docs

## What Was Implemented

### 1. Handoff Document (`/app/memory/appstore_submission_handoff.md`)
- **Item 8**: Full App Store Connect data collection questionnaire with 22 Apple data sub-types mapped to backend collections and mobile SDKs
- **Item 9**: Mapbox token wiring documentation (public vs secret, env vars, EAS Secrets, security checklist)
- **Item 10**: Screenshot sizes, 5 recommended screens with captions, 4 capture methods

### 2. Code: Mapbox `__DEV__` Guard (`/app/mobile/app/_layout.tsx`)
- Added `useEffect` at root layout that checks `EXPO_PUBLIC_MAPBOX_TOKEN` on mount
- `__DEV__` gated: only runs in development, early-returns in production
- Logs `console.warn` if token is missing or starts with `pk.REPLACE_ME`

### 3. Code: `.env.example` Update (`/app/mobile/.env.example`)
- Added annotated entries for `EXPO_PUBLIC_MAPBOX_TOKEN=pk.REPLACE_ME` and `RNMAPBOX_MAPS_DOWNLOAD_TOKEN=sk.REPLACE_ME`
- Included scope restrictions, bundle ID restriction, and EAS Secrets guidance in comments

## Web-to-Mobile Mapping
N/A — this iteration is documentation + dev tooling only.

## Known Issues
- **Pre-existing**: Mapbox web CSS bundling error (`mapbox-gl/dist/mapbox-gl.css` unresolvable in web bundle). Not caused by P11c. DailyRouteMap needs a `.web.tsx` stub that avoids importing `@rnmapbox/maps`.
- **Pre-existing**: Several Jest test suites have legacy failures unrelated to P11c.

## Dependencies Installed
None.
