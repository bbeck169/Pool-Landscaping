// metro.config.js
const { getDefaultConfig } = require("expo/metro-config");
const path = require('path');
const { FileStore } = require('metro-cache');

const config = getDefaultConfig(__dirname);

// Use a stable on-disk store (shared across web/android)
const root = process.env.METRO_CACHE_ROOT || path.join(__dirname, '.metro-cache');
config.cacheStores = [
  new FileStore({ root: path.join(root, 'cache') }),
];

/* ═══════════════════════════════════════════════════════════════════
 * Resolver shim: react-native-webrtc → event-target-shim/index
 * ───────────────────────────────────────────────────────────────────
 * `react-native-webrtc@124` does `import "event-target-shim/index"`,
 * a deep specifier absent from `event-target-shim`'s `exports` map
 * (which only exposes `.`, `./es5`, `./umd`, `./package.json`).
 * Metro's fast resolver enforces the exports map strictly, so the
 * static walk performed by expo-router's `require.context("./app")`
 * halts at ``[channelId].tsx → LivePanel → react-native-webrtc →
 * event-target-shim/index``, crashing `expo export` (which then
 * fails Cloud Build Step #9 `eas-update`).
 *
 * The lazy-require workaround does NOT help — Metro statically
 * analyses string-literal `require()` the same as top-level imports,
 * so the bad specifier is still walked. The only surgical fix is to
 * intercept resolution at the Metro layer and rewrite the deep
 * specifier to the package root, which the exports map DOES expose.
 * ═══════════════════════════════════════════════════════════════════ */
const upstreamResolveRequest = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName === 'event-target-shim/index') {
    return context.resolveRequest(context, 'event-target-shim', platform);
  }
  if (typeof upstreamResolveRequest === 'function') {
    return upstreamResolveRequest(context, moduleName, platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};


// // Exclude unnecessary directories from file watching
// config.watchFolders = [__dirname];
// config.resolver.blacklistRE = /(.*)\/(__tests__|android|ios|build|dist|.git|node_modules\/.*\/android|node_modules\/.*\/ios|node_modules\/.*\/windows|node_modules\/.*\/macos)(\/.*)?$/;

// // Alternative: use a more aggressive exclusion pattern
// config.resolver.blacklistRE = /node_modules\/.*\/(android|ios|windows|macos|__tests__|\.git|.*\.android\.js|.*\.ios\.js)$/;

// Reduce the number of workers to decrease resource usage
config.maxWorkers = 2;

module.exports = config;
