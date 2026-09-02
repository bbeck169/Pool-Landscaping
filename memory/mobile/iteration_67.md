# Iteration 67 — Phase K29 Parts 2 & 3: Finalize app.config.js + Mapbox secret cleanup

## What was done
- **Deleted `mobile/app.json`** — Expo now reads config exclusively from `mobile/app.config.js`
- **Cleaned `.env`** — Removed `RNMAPBOX_MAPS_DOWNLOAD_TOKEN=sk.eyJ1...` secret token and its 5-line comment block
- **Validated**:
  - `npx expo config --json` — successfully resolved all env vars into the config
  - `npx expo-doctor` — 18/18 checks passed (SDK 54 alignment confirmed)
  - Screenshot — app renders correctly on localhost:3001

## Config Schema (verified correct)
- **iOS**: `ios.config.googleMapsApiKey` → flat string (correct per Apple/Expo docs)
- **Android**: `android.config.googleMaps.apiKey` → nested object (correct per Android/Expo docs)
- **Mapbox**: `extra.mapboxToken` → reads `EXPO_PUBLIC_MAPBOX_TOKEN` (public `pk.` only)

## Security
- No `sk.` tokens remain in `.env` or any tracked file
- User MUST revoke the Mapbox `sk.` token from https://account.mapbox.com/access-tokens/ since it was previously committed to version control

## Dependencies
- No new dependencies installed in this iteration

## Known Issues
- Expo Preview Tunnel still intermittent (workaround: use localhost:3001 for screenshots)
