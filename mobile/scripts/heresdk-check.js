#!/usr/bin/env node
/**
 * Phase K39b · Feb-2026 — postinstall guard.
 *
 * Prints a friendly warning when the HERE SDK binaries aren't
 * present.  Exits 0 unconditionally so ``yarn install`` never fails
 * because of an optional-mode dependency — Google mode (the K39b
 * default) does not need HERE binaries.  Docs for the drop live in
 * ``mobile/heresdk/README.md``.
 */
const path = require("path");
const fs = require("fs");

const root = path.resolve(__dirname, "..", "heresdk");
const android = path.join(root, "android", "heresdk.aar");
const ios = path.join(root, "ios", "heresdk.xcframework");

const androidOk = fs.existsSync(android);
const iosOk = fs.existsSync(ios);

if (!androidOk || !iosOk) {
  const missing = [
    !androidOk ? "android/heresdk.aar" : null,
    !iosOk ? "ios/heresdk.xcframework/" : null,
  ]
    .filter(Boolean)
    .join(", ");
  // eslint-disable-next-line no-console
  console.log(
    "\n[K39b] HERE SDK binaries not present (" +
      missing +
      "). HERE mode will render a " +
      '"Map unavailable" placeholder. Follow mobile/heresdk/README.md ' +
      "to enable HERE tiles in a dev-client / EAS build. Google " +
      "mode (default) is unaffected.\n",
  );
}
process.exit(0);
