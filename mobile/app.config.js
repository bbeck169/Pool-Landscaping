/**
 * app.config.js — Phase K29 · Dynamic Expo config.
 *
 * Replaces the static app.json so that Google Maps API keys and the
 * Mapbox token are read from process.env at build time instead of
 * relying on static "$ENV_VAR" string substitution.
 *
 * K20 map guards handle empty-key gracefully (MapUnavailablePlaceholder).
 *
 * NOTE: exported as a static CommonJS object, not a config function.
 * Emergent's eas-update build step does `require('./app.config.js')`
 * then `config.default || config` WITHOUT calling it — on Node 24 that
 * require() auto-detects `export default (...) => {...}` as ESM and
 * returns the un-invoked function, so JSON.stringify(fn) is undefined
 * and app.json generation crashes. A plain object export sidesteps it;
 * env vars are still read at file-load time, so behavior is unchanged.
 */
module.exports = {
  expo: {
    name: "Pool & Landscaping of Vistancia",
    slug: "poolscape-audit",
    version: "1.0.0",
    orientation: "portrait",
    icon: "./assets/images/icon.png",
    splash: {
      image: "./assets/images/splash-image.png",
      resizeMode: "contain",
      backgroundColor: "#000000",
    },
    scheme: "frontend",
    userInterfaceStyle: "automatic",
    newArchEnabled: true,
    runtimeVersion: {
      policy: "fingerprint",
    },
    updates: {
      enabled: true,
      checkAutomatically: "ON_LOAD",
      fallbackToCacheTimeout: 0,
      url: "https://u.expo.dev/bdd4bc95-5d7c-46d8-8243-0b6ed1e9aa19",
    },

    /* ─── iOS ──────────────────────────────────────────────── */
    ios: {
      supportsTablet: true,
      bundleIdentifier: "com.emergent.poolappmobile.r03fw2",
      buildNumber: "2",
      config: {
        usesNonExemptEncryption: false,
        googleMapsApiKey: process.env.EXPO_PUBLIC_GOOGLE_MAPS_IOS_KEY || "",
      },
      privacyManifests: {
        NSPrivacyAccessedAPITypes: [
          {
            NSPrivacyAccessedAPIType:
              "NSPrivacyAccessedAPICategoryUserDefaults",
            NSPrivacyAccessedAPITypeReasons: ["CA92.1"],
          },
          {
            NSPrivacyAccessedAPIType:
              "NSPrivacyAccessedAPICategoryFileTimestamp",
            NSPrivacyAccessedAPITypeReasons: ["C617.1"],
          },
          {
            NSPrivacyAccessedAPIType:
              "NSPrivacyAccessedAPICategorySystemBootTime",
            NSPrivacyAccessedAPITypeReasons: ["35F9.1"],
          },
          {
            NSPrivacyAccessedAPIType:
              "NSPrivacyAccessedAPICategoryDiskSpace",
            NSPrivacyAccessedAPITypeReasons: ["E174.1"],
          },
        ],
        NSPrivacyCollectedDataTypes: [
          {
            NSPrivacyCollectedDataType:
              "NSPrivacyCollectedDataTypeEmailAddress",
            NSPrivacyCollectedDataTypeLinked: true,
            NSPrivacyCollectedDataTypeTracking: false,
            NSPrivacyCollectedDataTypePurposes: [
              "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
          },
          {
            NSPrivacyCollectedDataType: "NSPrivacyCollectedDataTypeName",
            NSPrivacyCollectedDataTypeLinked: true,
            NSPrivacyCollectedDataTypeTracking: false,
            NSPrivacyCollectedDataTypePurposes: [
              "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
          },
          {
            NSPrivacyCollectedDataType:
              "NSPrivacyCollectedDataTypePhoneNumber",
            NSPrivacyCollectedDataTypeLinked: true,
            NSPrivacyCollectedDataTypeTracking: false,
            NSPrivacyCollectedDataTypePurposes: [
              "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
          },
          {
            NSPrivacyCollectedDataType:
              "NSPrivacyCollectedDataTypePhysicalAddress",
            NSPrivacyCollectedDataTypeLinked: true,
            NSPrivacyCollectedDataTypeTracking: false,
            NSPrivacyCollectedDataTypePurposes: [
              "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
          },
          {
            NSPrivacyCollectedDataType:
              "NSPrivacyCollectedDataTypePreciseLocation",
            NSPrivacyCollectedDataTypeLinked: true,
            NSPrivacyCollectedDataTypeTracking: false,
            NSPrivacyCollectedDataTypePurposes: [
              "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
          },
        ],
        NSPrivacyTracking: false,
        NSPrivacyTrackingDomains: [],
      },
      infoPlist: {
        NSCameraUsageDescription:
          "Take before and after photos of service jobs",
        NSPhotoLibraryUsageDescription:
          "Attach job photos from your library",
        NSMicrophoneUsageDescription:
          "Record and stream audio for walkie-talkie live sessions",
        NSSpeechRecognitionUsageDescription:
          "Dictate job notes and task updates hands-free while on-site",
        NSLocationWhenInUseUsageDescription:
          "Your employer uses this to record location during your shift. Location is only collected while you are clocked in.",
        NSLocationAlwaysAndWhenInUseUsageDescription:
          "Your employer uses this to record location during your shift, including when the app is in the background. Location is only collected while you are clocked in.",
        UIBackgroundModes: ["fetch", "location", "audio"],
      },
    },

    /* ─── Android ──────────────────────────────────────────── */
    android: {
      adaptiveIcon: {
        foregroundImage: "./assets/images/adaptive-icon.png",
        backgroundColor: "#000000",
      },
      edgeToEdgeEnabled: true,
      config: {
        googleMaps: {
          apiKey: process.env.EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY || "",
        },
      },
      versionCode: 2,
      package: "com.emergent.poolappmobile.r03fw2",
      permissions: [
        "ACCESS_BACKGROUND_LOCATION",
        "ACCESS_COARSE_LOCATION",
        "ACCESS_FINE_LOCATION",
        "CAMERA",
        "FOREGROUND_SERVICE",
        "FOREGROUND_SERVICE_LOCATION",
        "FOREGROUND_SERVICE_MICROPHONE",
        "MODIFY_AUDIO_SETTINGS",
        "POST_NOTIFICATIONS",
        "READ_MEDIA_IMAGES",
        "READ_MEDIA_VIDEO",
        "RECORD_AUDIO",
      ],
    },

    /* ─── Web ──────────────────────────────────────────────── */
    web: {
      bundler: "metro",
      output: "single",
      favicon: "./assets/images/favicon.png",
    },

    /* ─── Plugins ──────────────────────────────────────────── */
    plugins: [
      "expo-router",
      [
        "expo-splash-screen",
        {
          image: "./assets/images/splash-image.png",
          imageWidth: 200,
          resizeMode: "contain",
          backgroundColor: "#000000",
        },
      ],
      "@react-native-community/datetimepicker",
      [
        "expo-location",
        {
          locationWhenInUsePermission:
            "Location is used only during your active work shift, per your employer's agreement.",
          locationAlwaysAndWhenInUsePermission:
            "Location is used only during your active work shift, per your employer's agreement.",
          isAndroidBackgroundLocationEnabled: true,
          isAndroidForegroundServiceEnabled: true,
        },
      ],
      // Phase K46 · Feb-2026 — ``@rnmapbox/maps`` plugin removed.
      //
      //   Mapbox's native initializer was the root cause of the
      //   Phase K45 Android white-screen crash — the module's
      //   Objective-C / Java constructor threw before any JS runs
      //   when the access token wasn't wired at build time,
      //   blanking the shell. K46 rips Mapbox out entirely and
      //   standardises on Google Maps via ``react-native-maps``.
      //   See ``memory/PHASE_K46_GOOGLE_MAPS_MIGRATION.md`` for
      //   the full migration rationale. ``react-native-maps`` does
      //   not require a config plugin — its Google Maps API keys
      //   are consumed directly from ``ios.config.googleMapsApiKey``
      //   / ``android.config.googleMaps.apiKey`` above. An EAS
      //   rebuild is required after K46 lands because the native
      //   auto-linked manifest changes.
      [
        "expo-audio",
        {
          microphonePermission:
            "Allow Pool Landscaping to record audio walkie-talkie clips.",
          recordAudioAndroid: true,
        },
      ],
      "@config-plugins/react-native-webrtc",
      [
        "@stripe/stripe-react-native",
        {
          enableGooglePay: false,
        },
      ],
      "expo-asset",
      // Phase K45b · Feb-2026 — HERE Maps plugin registration removed.
      //
      //   The `react-native-here-explore` JS dep is not in `package.json`
      //   and never was during the K45 → K45b window; the .aar /
      //   .xcframework binaries have never been dropped into
      //   `mobile/heresdk/`; and `EXPO_PUBLIC_HERE_ACCESS_KEY_ID`
      //   defaults to empty in every environment. Keeping a plugin
      //   entry here — even guarded — is dead weight and a footgun
      //   for anyone trying to re-enable HERE later. To re-enable,
      //   follow `mobile/heresdk/README.md`:
      //     1. `yarn add react-native-here-explore`
      //     2. Drop the SDK binaries into `mobile/heresdk/`
      //     3. Re-register the plugin here, guarded on the env key.
    ],

    /* ─── Extra ────────────────────────────────────────────── */
    extra: {
      // Phase K46 · Feb-2026 — ``mapboxToken`` removed. Mapbox has
      // been ripped out of the mobile stack (see plugins block
      // above). Any lingering runtime reads of
      // ``Constants.expoConfig.extra.mapboxToken`` will read as
      // ``undefined`` — the K46 map surfaces all use
      // ``hasGoogleMapsKey()`` from ``@/src/utils/mapsKey`` instead.
      eas: {
        projectId: "bdd4bc95-5d7c-46d8-8243-0b6ed1e9aa19",
      },
    },

    experiments: {
      typedRoutes: true,
    },
  },
};
