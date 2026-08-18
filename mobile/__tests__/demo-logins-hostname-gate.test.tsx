/**
 * Feb-2026 · Mobile demo-tiles hostname strict gate.
 *
 * Source-inspection contract test mirroring
 * ``frontend/src/test/demo-logins-hostname-gate.test.jsx``. Asserts:
 *   1. Mobile login imports the shared ``isPreviewOrDev()`` helper.
 *   2. ``showDemoTiles`` composes the hostname gate AND the server
 *      flag — either false → tiles hidden.
 *   3. The helper falls back to ``false`` (production posture) when
 *      the backend host is anything other than preview / dev.
 */
import fs from "fs";
import path from "path";

const loginSrc = fs.readFileSync(
  path.resolve(__dirname, "../app/login.tsx"),
  "utf8",
);
const envSrc = fs.readFileSync(
  path.resolve(__dirname, "../src/utils/env.ts"),
  "utf8",
);

describe("Mobile demo-tiles · hostname strict gate", () => {
  it("imports isPreviewOrDev from the shared util", () => {
    expect(loginSrc).toMatch(
      /import\s+\{\s*isPreviewOrDev\s*\}\s+from\s+["']@\/src\/utils\/env["']/,
    );
  });

  it("composes hostname + server flag — either false hides the tiles", () => {
    expect(loginSrc).toMatch(/hostAllowed\s*=\s*React\.useMemo\(\(\)\s*=>\s*isPreviewOrDev\(\)/);
    expect(loginSrc).toMatch(
      /showDemoTiles\s*=\s*hostAllowed\s*&&\s*demoServerAllowed\s*===\s*true/,
    );
  });

  it("prefers /config/features and falls back to /config/public.app_env", () => {
    expect(loginSrc).toMatch(/\.get\(["']\/config\/features["']\)/);
    expect(loginSrc).toMatch(/demo_logins_enabled/);
    expect(loginSrc).toMatch(/\.get\(["']\/config\/public["']\)/);
  });

  it("helper: preview.emergentagent.com host returns true", () => {
    expect(envSrc).toMatch(/\.endsWith\(["']\.preview\.emergentagent\.com["']\)/);
    // Fail-closed default outside the recognised set.
    expect(envSrc).toMatch(/return\s+false;\s*\}\s*$/m);
  });

  it("helper: __DEV__ short-circuits to true", () => {
    expect(envSrc).toMatch(/typeof\s+__DEV__\s*!==\s*["']undefined["']\s*&&\s*__DEV__/);
  });
});
