# HERE Maps SDK · Currently DISABLED (K45b · Feb-2026)

**Status:** HERE Maps support is disabled at the package.json and Expo
config plugin level. The K45 lazy-require + `.MISSING` marker + runtime
provider downgrade infrastructure is still in place as a belt for any
future re-enable path — but `react-native-here-explore` is not
installed and its plugin is not registered.

## Why disabled?

- No environment we ship to has `EXPO_PUBLIC_HERE_ACCESS_KEY_ID` set.
- The `.aar` / `.xcframework` native binaries have never been dropped
  into this folder.
- Keeping the JS dep and the Expo plugin registered — even guarded —
  was diagnosed as a candidate for the K45b Android white-screen
  regression. Expo autolinking picks up native modules on presence in
  `package.json`, independent of whether any JS ever imports them. The
  safer default is "not installed at all".

## What's still here?

Everything K45 shipped except the JS dep itself:

- `mobile/scripts/heresdk-check.js` — postinstall hook that writes a
  `.MISSING` marker and regenerates
  `mobile/src/lib/maps/heresdkStatus.generated.ts` with the current
  binary-presence state.
- `mobile/src/lib/maps/heresdkStatus.generated.ts` — bundled constant
  read by `provider.ts` for runtime `here → google` downgrade.
- `mobile/src/lib/maps/hereAdapter.tsx` — a hard-throw sentinel that
  keeps `index.ts`'s conditional `require("./hereAdapter")` safe.
- `mobile/__tests__/k45b-here-removed.test.ts` — regression guard
  that fails CI if HERE is quietly re-added.

## How to re-enable HERE (if we ever ship it for real)

1. `yarn add react-native-here-explore` (whichever version the SDK
   drop is compatible with — pin exactly).
2. Drop the native binaries:
   - Android: `mobile/heresdk/android/heresdk.aar`
   - iOS:     `mobile/heresdk/ios/heresdk.xcframework/`
   (Both are shipped by HERE via their partner portal; do NOT commit
   them.  Store in EAS secrets + drop at prebuild time.)
3. Re-register the plugin in `mobile/app.config.js` (guarded on the
   env key), example:

   ```js
   ...(process.env.EXPO_PUBLIC_HERE_ACCESS_KEY_ID
     ? [
         [
           "react-native-here-explore",
           {
             accessKeyId: process.env.EXPO_PUBLIC_HERE_ACCESS_KEY_ID,
             accessKeySecret: process.env.HERE_ACCESS_KEY_SECRET,
           },
         ],
       ]
     : []),
   ```

4. Restore `hereAdapter.tsx` to the K45 lazy-require implementation
   (git history has the diff — search for `_loadHere` in the K45 ship
   commit).
5. Delete `mobile/__tests__/k45b-here-removed.test.ts` — it exists
   only to enforce the current "disabled" state.
6. Set `EXPO_PUBLIC_HERE_ACCESS_KEY_ID` in your EAS build environment
   and cut a **new EAS build** (not OTA — package.json + native
   manifest both changed).
