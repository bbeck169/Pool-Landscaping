/**
 * OTA Auto-Update configuration test.
 *
 * Verifies that the Expo config and eas.json are correctly set up
 * for over-the-air updates on both iOS and Android.
 */
import * as fs from "fs";
import * as path from "path";

describe("OTA Auto-Update Configuration", () => {
  // Load the app config by requiring the CommonJS module directly.
  const appConfig = require("../app.config.js");
  const expo = appConfig.expo || appConfig;

  const easJson = JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "../eas.json"), "utf-8"),
  );

  it("expo.updates.enabled is true", () => {
    expect(expo.updates).toBeDefined();
    expect(expo.updates.enabled).toBe(true);
  });

  it("expo.updates.checkAutomatically is ON_LOAD", () => {
    expect(expo.updates.checkAutomatically).toBe("ON_LOAD");
  });

  it("expo.updates.fallbackToCacheTimeout is 0 (never block UI)", () => {
    expect(expo.updates.fallbackToCacheTimeout).toBe(0);
  });

  it("expo.updates.url points to the EAS Update CDN", () => {
    expect(expo.updates.url).toMatch(
      /^https:\/\/u\.expo\.dev\/[a-f0-9-]+$/,
    );
  });

  it("expo.runtimeVersion uses a valid policy", () => {
    expect(expo.runtimeVersion).toBeDefined();
    // Should be an object with a policy key (not a hard-coded string)
    expect(expo.runtimeVersion.policy).toBeDefined();
    expect(["fingerprint", "appVersion", "sdkVersion", "nativeVersion"]).toContain(
      expo.runtimeVersion.policy,
    );
  });

  it("eas.json has development/preview/production channels", () => {
    expect(easJson.build.development.channel).toBe("development");
    expect(easJson.build.preview.channel).toBe("preview");
    expect(easJson.build.production.channel).toBe("production");
  });

  it("expo-updates is installed and compatible with Expo SDK 54", () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, "../package.json"), "utf-8"),
    );
    expect(pkg.dependencies["expo-updates"]).toBeDefined();
    // Should be ~29.x for SDK 54
    expect(pkg.dependencies["expo-updates"]).toMatch(/^~?29\./);
  });

  it("both iOS and Android inherit top-level updates config (no platform overrides)", () => {
    // If ios.updates or android.updates exist, they would override the
    // top-level config. We don't want that — both platforms should use
    // the same OTA config.
    expect(expo.ios?.updates).toBeUndefined();
    expect(expo.android?.updates).toBeUndefined();
  });

  it("documentation file exists", () => {
    const docPath = path.resolve(__dirname, "../../memory/OTA_AUTO_UPDATE_CONFIG.md");
    expect(fs.existsSync(docPath)).toBe(true);
    const content = fs.readFileSync(docPath, "utf-8");
    expect(content).toContain("OTA");
    expect(content).toContain("fingerprint");
    expect(content).toContain("binary build");
  });
});
