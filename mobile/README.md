# Pool & Landscaping of Vistancia — Mobile App

Expo/React Native mobile app for the Pool & Landscaping of Vistancia CRM platform.

## Get started

1. Install dependencies

   ```bash
   yarn install
   ```

2. Start the app

   ```bash
   npx expo start
   ```

In the output, you'll find options to open the app in a

- [development build](https://docs.expo.dev/develop/development-builds/introduction/)
- [Android emulator](https://docs.expo.dev/workflow/android-studio-emulator/)
- [iOS simulator](https://docs.expo.dev/workflow/ios-simulator/)
- [Expo Go](https://expo.dev/go), a limited sandbox for trying out app development with Expo

This project uses [file-based routing](https://docs.expo.dev/router/introduction) via Expo Router.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values. Key variables:

| Variable | Purpose |
|---|---|
| `EXPO_PUBLIC_BACKEND_URL` | Backend API base URL |
| `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` | Stripe publishable key for payments |
| `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY` | Google Maps JS API key (shared/legacy) |
| `EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY` | Google Maps API key for Android builds |
| `EXPO_PUBLIC_GOOGLE_MAPS_IOS_KEY` | Google Maps API key for iOS builds |
| `EXPO_PUBLIC_MAPBOX_TOKEN` | Mapbox public access token |
| `RNMAPBOX_MAPS_DOWNLOAD_TOKEN` | Mapbox secret download token (build-time only) |

---

## Setting Up EAS Secrets (Google Maps & Mapbox)

### Why?

The Android native `react-native-maps` `MapView` **crashes on init** if the Google Maps API key is missing from `AndroidManifest.xml`. EAS builds derive this manifest entry from `app.json`, which references environment variables via `$`-interpolation. You **must** set these secrets in EAS before building.

### Steps

1. **Create API keys** in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
   - Enable **Maps SDK for Android** and **Maps SDK for iOS**.
   - Create separate keys per platform (recommended) or use a single key.
   - Restrict the Android key to your app's package name (`com.emergent.poolappmobile.r03fw2`).
   - Restrict the iOS key to your app's bundle identifier.

2. **Set the secrets in EAS**:

   ```bash
   eas secret:create --name EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY --value "AIzaSy..."
   eas secret:create --name EXPO_PUBLIC_GOOGLE_MAPS_IOS_KEY --value "AIzaSy..."
   ```

3. **Mapbox tokens** (for dispatch map + daily route map):

   ```bash
   eas secret:create --name EXPO_PUBLIC_MAPBOX_TOKEN --value "pk.eyJ1..."
   eas secret:create --name RNMAPBOX_MAPS_DOWNLOAD_TOKEN --value "sk.eyJ1..."
   ```

   - The public `pk.` token is used at runtime.
   - The secret `sk.` token (with `DOWNLOADS:READ` scope) is used at build time by the `@rnmapbox/maps` plugin to download the native SDK.

4. **Verify** the keys appear in `app.json` config:

   ```json
   "android": {
     "config": {
       "googleMaps": {
         "apiKey": "$EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY"
       }
     }
   },
   "ios": {
     "config": {
       "googleMaps": {
         "apiKey": "$EXPO_PUBLIC_GOOGLE_MAPS_IOS_KEY"
       }
     }
   }
   ```

5. **Build** with EAS:

   ```bash
   eas build --platform android --profile production
   eas build --platform ios --profile production
   ```

### Safety Guards (Phase K20)

All native map components have safety guards that render a graceful `<MapUnavailablePlaceholder />` instead of crashing when an API key is missing:

| Component | Map Provider | Key Checked |
|---|---|---|
| `MeasureMap.native.tsx` | Google Maps (`react-native-maps`) | `hasGoogleMapsKey()` |
| `ScheduleMap.native.tsx` | Google Maps (`react-native-maps`) | `hasGoogleMapsKey()` |
| `MapCanvas.native.tsx` | Google Maps (`react-native-maps`) | `hasGoogleMapsKey()` |
| `DailyRouteMap.native.tsx` | Mapbox (`@rnmapbox/maps`) | `hasMapboxToken()` |
| `LiveTechPinsMap.tsx` | Mapbox (`@rnmapbox/maps`) | `hasMapboxToken()` |

Central utility: `src/utils/mapsKey.tsx`

---

## Learn more

- [Expo documentation](https://docs.expo.dev/)
- [Learn Expo tutorial](https://docs.expo.dev/tutorial/introduction/)
- [Expo on GitHub](https://github.com/expo/expo)
- [Discord community](https://chat.expo.dev)
