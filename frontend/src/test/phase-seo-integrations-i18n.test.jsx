/**
 * Sep-2026 · DataForSEO card · i18n key coverage across en/es/fr.
 */
import { describe, it, expect } from "vitest";
import commonEN from "../i18n/locales/en/common.json";
import commonES from "../i18n/locales/es/common.json";
import commonFR from "../i18n/locales/fr/common.json";

const REQUIRED_KEYS = [
  "integrations.dataforseo.title",
  "integrations.dataforseo.description",
  "integrations.dataforseo.status.configured",
  "integrations.dataforseo.status.default",
  "integrations.dataforseo.login_label",
  "integrations.dataforseo.password_label",
  "integrations.dataforseo.save",
  "integrations.dataforseo.saved",
  "integrations.dataforseo.test",
  "integrations.dataforseo.test_ok",
  "integrations.dataforseo.test_fail",
  "integrations.dataforseo.change",
  "integrations.dataforseo.cancel",
  "integrations.dataforseo.remove",
  "integrations.dataforseo.removed",
  "integrations.dataforseo.remove_confirm",
  "integrations.dataforseo.remove_confirm_yes",
  "integrations.dataforseo.remove_confirm_no",
  "integrations.dataforseo.last_verified",
];

function _get(obj, dotted) {
  return dotted.split(".").reduce(
    (a, k) => (a && typeof a === "object" ? a[k] : undefined), obj,
  );
}

describe("integrations.dataforseo i18n coverage (en/es/fr)", () => {
  for (const key of REQUIRED_KEYS) {
    it(`en / es / fr all define ${key}`, () => {
      expect(_get(commonEN, key), `en missing ${key}`).toBeTruthy();
      expect(_get(commonES, key), `es missing ${key}`).toBeTruthy();
      expect(_get(commonFR, key), `fr missing ${key}`).toBeTruthy();
    });
  }

  it("locales use language-appropriate label wording", () => {
    expect(_get(commonEN, "integrations.dataforseo.login_label")).toBe("Login");
    expect(_get(commonES, "integrations.dataforseo.login_label")).toBe("Usuario");
    expect(_get(commonFR, "integrations.dataforseo.login_label")).toBe("Identifiant");
  });

  it("interpolation tokens {{ms}} and {{when}} preserved across locales", () => {
    for (const c of [commonEN, commonES, commonFR]) {
      expect(_get(c, "integrations.dataforseo.test_ok"))
        .toMatch(/\{\{ms\}\}/);
      expect(_get(c, "integrations.dataforseo.last_verified"))
        .toMatch(/\{\{when\}\}/);
    }
  });
});
