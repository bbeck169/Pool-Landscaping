/**
 * SP3 · Feb-2026 — Signup i18n labels render in en / es / fr.
 *
 * Confirms Part F's ES + FR ``signup.*`` namespace additions match
 * the EN namespace shape, so a locale swap actually finds keys.
 */
import { describe, it, expect } from "vitest";
import commonEN from "../i18n/locales/en/common.json";
import commonES from "../i18n/locales/es/common.json";
import commonFR from "../i18n/locales/fr/common.json";

const REQUIRED_SIGNUP_KEYS = [
  "signup.title",
  "signup.subtitle",
  "signup.submit",
  "signup.submitting",
  "signup.submitted",
  "signup.card_placeholder",
  "signup.card_label",
  "signup.fields.business_name",
  "signup.fields.admin_name",
  "signup.fields.admin_email",
  "signup.fields.admin_password",
  "signup.fields.admin_phone",
  "signup.fields.primary_industry",
  "signup.fields.country",
  "signup.errors.weak_password",
  "signup.errors.invalid_industry",
  "signup.errors.invalid_country",
  "signup.errors.email_already_registered",
  "signup.errors.rate_limited",
  "signup.verify.title",
  "signup.verify.ok",
  "signup.verify.failed",
  "signup.email_sent.title",
];

const REQUIRED_ONBOARDING_KEYS = [
  "onboarding.title",
  "onboarding.next",
  "onboarding.finish",
  "onboarding.step_1.title",
  "onboarding.step_2.title",
  "onboarding.step_3.title",
  "onboarding.step_4.title",
  "onboarding.step_4.primary_hint",
];

function _get(obj, dotted) {
  return dotted.split(".").reduce(
    (acc, k) => (acc && typeof acc === "object" ? acc[k] : undefined), obj,
  );
}

describe("SP3 · Signup + Onboarding i18n keys (en/es/fr)", () => {
  for (const key of REQUIRED_SIGNUP_KEYS) {
    it(`en / es / fr all define ${key}`, () => {
      expect(_get(commonEN, key), `en missing ${key}`).toBeTruthy();
      expect(_get(commonES, key), `es missing ${key}`).toBeTruthy();
      expect(_get(commonFR, key), `fr missing ${key}`).toBeTruthy();
    });
  }
  for (const key of REQUIRED_ONBOARDING_KEYS) {
    it(`en / es / fr all define ${key}`, () => {
      expect(_get(commonEN, key), `en missing ${key}`).toBeTruthy();
      expect(_get(commonES, key), `es missing ${key}`).toBeTruthy();
      expect(_get(commonFR, key), `fr missing ${key}`).toBeTruthy();
    });
  }

  it("card_label uses correct language-specific wording", () => {
    expect(_get(commonEN, "signup.card_label")).toMatch(/Payment card/i);
    expect(_get(commonES, "signup.card_label")).toMatch(/Tarjeta/i);
    expect(_get(commonFR, "signup.card_label")).toMatch(/Carte/i);
  });
});
