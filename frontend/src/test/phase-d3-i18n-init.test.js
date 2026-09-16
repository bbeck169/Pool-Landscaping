/**
 * Phase D3 · Feb 2026 — i18n init smoke.
 *
 * Boots the module by importing it, then asserts the three shipped
 * locales are loaded and a sample common-namespace key resolves in
 * each.
 */
import { describe, it, expect, beforeAll } from "vitest";

let i18n;

beforeAll(async () => {
  const mod = await import("../i18n");
  i18n = mod.default;
});


describe("Phase D3 · i18n init", () => {
  it("boots without error", () => {
    expect(i18n).toBeDefined();
    expect(typeof i18n.changeLanguage).toBe("function");
  });

  it("fallbackLng is en", () => {
    // ``fallbackLng`` on i18next may be stored as a string OR an
    // array depending on version; normalise for the assertion.
    const fb = i18n.options.fallbackLng;
    const asArr = Array.isArray(fb) ? fb : [fb];
    expect(asArr).toContain("en");
  });

  it("bundles the 3 supported locales", () => {
    // ``store.data`` carries the loaded bundles keyed by locale.
    const data = i18n.store.data;
    expect(Object.keys(data).sort()).toEqual(["en", "es", "fr"]);
  });

  it("common.save resolves in all three locales", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("common:save")).toBe("Save");
    await i18n.changeLanguage("es");
    expect(i18n.t("common:save")).toBe("Guardar");
    await i18n.changeLanguage("fr");
    expect(i18n.t("common:save")).toBe("Enregistrer");
  });

  it("checklist namespace resolves in all three locales", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("checklist:industry_form_title")).toBe("Industry checklist");
    await i18n.changeLanguage("es");
    expect(i18n.t("checklist:industry_form_title")).toBe(
      "Lista de verificación por industria",
    );
    await i18n.changeLanguage("fr");
    expect(i18n.t("checklist:industry_form_title")).toBe(
      "Liste de contrôle par secteur",
    );
  });

  it("industry display names resolve for a sample slug per locale", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("industries:hvac")).toBe("HVAC");
    await i18n.changeLanguage("es");
    expect(i18n.t("industries:hvac")).toBe("HVAC");
    await i18n.changeLanguage("fr");
    expect(i18n.t("industries:hvac")).toBe("CVC");

    await i18n.changeLanguage("es");
    expect(i18n.t("industries:carpet_cleaning")).toBe("Limpieza de alfombras");
    await i18n.changeLanguage("fr");
    expect(i18n.t("industries:carpet_cleaning")).toBe("Nettoyage de tapis");
  });
});
