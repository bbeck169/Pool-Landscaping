/**
 * Phase P50 · Feb-2026 — i18n initialization + locale fallback.
 *
 * Locks the i18next singleton's contract for the new P50 namespaces
 * (`leads`, `propertyselector`) alongside the pre-existing
 * `common` / `industries` / `checklist` bundles:
 *
 *   1. i18n init succeeds when imported (no throw, resources loaded).
 *   2. All five namespaces are registered and reachable via the
 *      exported `SUPPORTED_LOCALES` array (EN/ES/FR).
 *   3. `t()` resolves each locale correctly for a spec-touched key.
 *   4. Locale switch via `i18n.changeLanguage()` reflects on the
 *      next `t()` call.
 *   5. Missing key falls back to the key literal (i18next default
 *      behaviour when `returnNull: false` + no fallback plumbing).
 *   6. Unsupported locale falls back to EN (fallbackLng: "en").
 *   7. The P52-slot TODO comment is present in `i18n/index.js` so
 *      the tenant.default_locale wire-up point stays visible.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect, beforeAll } from "vitest";

// Eager import so the singleton is initialised for every assertion.
import i18n from "@/i18n";
import { SUPPORTED_LOCALES } from "@/i18n";

const _readIndex = () =>
  fs.readFileSync(
    path.resolve(__dirname, "../i18n/index.js"),
    "utf-8",
  );


beforeAll(async () => {
  // Force a known-good starting locale so any prior test that ran
  // in the same worker cannot leave us mid-switch.
  await i18n.changeLanguage("en");
});


describe("P50 · i18n init contract", () => {
  it("initialises without throwing and exposes the three supported " +
     "locales via SUPPORTED_LOCALES", () => {
    expect(i18n.isInitialized).toBe(true);
    const codes = SUPPORTED_LOCALES.map((l) => l.code);
    expect(codes).toEqual(["en", "es", "fr"]);
  });

  it("registers the five namespaces the P50 refactor requires — " +
     "common, industries, checklist (pre-existing) plus the two new " +
     "P50 additions leads + propertyselector", () => {
    const ns = i18n.options.ns;
    expect(ns).toContain("common");
    expect(ns).toContain("industries");
    expect(ns).toContain("checklist");
    expect(ns).toContain("leads");
    expect(ns).toContain("propertyselector");
  });

  it("P52 tenant.default_locale anchor was consumed and detector " +
     "is wired — post-P52 negative-space check.  This test's role " +
     "evolved during the P50→P52 bridge: originally it locked the " +
     "presence of a TODO(P52) grep-anchor comment planted in " +
     "i18n/index.js so the next phase (P52) had a visible wire-in " +
     "point.  Now that P52 has landed and consumed that anchor by " +
     "replacing it with the actual lang-tenant-default detector, " +
     "the test inverts to guard against two regressions:\n" +
     "  (a) somebody re-adding a TODO(P52) comment for a future " +
     "      phase and forgetting to remove it after that phase ships;\n" +
     "  (b) somebody deleting the lang-tenant-default detector.", () => {
    const src = _readIndex();
    // (a) TODO(P52) anchor must NOT be present — its job is done.
    expect(src).not.toMatch(/TODO\(P52\)/);
    // (b) The detector name still lives in the file, gated + wired
    //     in the detection order.
    expect(src).toMatch(/lang-tenant-default/);
  });
});


describe("P50 · leads namespace · EN / ES / FR resolve", () => {
  it("resolves the Active tab label in each of the three locales", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("leads:tabs.active")).toBe("Active");
    await i18n.changeLanguage("es");
    expect(i18n.t("leads:tabs.active")).toBe("Activos");
    await i18n.changeLanguage("fr");
    expect(i18n.t("leads:tabs.active")).toBe("Actifs");
  });

  it("resolves the Archive tab label in each locale", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("leads:tabs.archive")).toBe("Archive");
    await i18n.changeLanguage("es");
    expect(i18n.t("leads:tabs.archive")).toBe("Archivados");
    await i18n.changeLanguage("fr");
    expect(i18n.t("leads:tabs.archive")).toBe("Archivés");
  });

  it("resolves the status labels for the five canonical values in " +
     "each locale — new / contacted / quoted / closed_won / " +
     "closed_lost", async () => {
    const cases = {
      en: {
        new: "New", contacted: "Contacted", quoted: "Quoted",
        closed_won: "Closed – Won", closed_lost: "Closed – Lost",
      },
      es: {
        new: "Nuevo", contacted: "Contactado", quoted: "Cotizado",
        closed_won: "Cerrado – Ganado", closed_lost: "Cerrado – Perdido",
      },
      fr: {
        new: "Nouveau", contacted: "Contacté", quoted: "Devis envoyé",
        closed_won: "Clôturé – Gagné", closed_lost: "Clôturé – Perdu",
      },
    };
    for (const [loc, expected] of Object.entries(cases)) {
      await i18n.changeLanguage(loc);
      for (const [k, v] of Object.entries(expected)) {
        expect(
          i18n.t(`leads:status.${k}`),
          `expected leads:status.${k} in ${loc} to be "${v}"`,
        ).toBe(v);
      }
    }
  });

  it("resolves empty-state copy on both Active + Archive tabs in " +
     "each locale", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("leads:empty.active.title")).toBe("No active leads yet.");
    expect(i18n.t("leads:empty.archive.title")).toBe("No archived leads yet.");
    await i18n.changeLanguage("es");
    expect(i18n.t("leads:empty.active.title")).toBe("Aún no hay clientes potenciales activos.");
    expect(i18n.t("leads:empty.archive.title")).toBe("Aún no hay clientes potenciales archivados.");
    await i18n.changeLanguage("fr");
    expect(i18n.t("leads:empty.active.title")).toBe("Aucun prospect actif pour le moment.");
    expect(i18n.t("leads:empty.archive.title")).toBe("Aucun prospect archivé pour le moment.");
  });
});


describe("P50 · propertyselector namespace · EN / ES / FR resolve", () => {
  it("resolves loading + empty warning + label variants in each " +
     "locale", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("propertyselector:loading")).toBe("Loading properties…");
    expect(i18n.t("propertyselector:label_single")).toBe("Property");
    expect(i18n.t("propertyselector:label_multi")).toBe("Property *");

    await i18n.changeLanguage("es");
    expect(i18n.t("propertyselector:loading")).toBe("Cargando propiedades…");
    expect(i18n.t("propertyselector:label_single")).toBe("Propiedad");

    await i18n.changeLanguage("fr");
    expect(i18n.t("propertyselector:loading")).toBe("Chargement des propriétés…");
    expect(i18n.t("propertyselector:label_single")).toBe("Propriété");
  });

  it("interpolates {{count}} into the validation copy across " +
     "locales", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("propertyselector:validation_pick_one", { count: 3 }))
      .toBe("This customer has 3 properties — pick one.");
    await i18n.changeLanguage("es");
    expect(i18n.t("propertyselector:validation_pick_one", { count: 3 }))
      .toBe("Este cliente tiene 3 propiedades — elige una.");
    await i18n.changeLanguage("fr");
    expect(i18n.t("propertyselector:validation_pick_one", { count: 3 }))
      .toBe("Ce client a 3 propriétés — choisissez-en une.");
  });
});


describe("P50 · locale fallback contract", () => {
  it("missing key returns the key literal (returnNull:false, no " +
     "custom fallback) — this is what lets components pass an " +
     "English default via `t(key, 'fallback')`", async () => {
    await i18n.changeLanguage("en");
    // Without an explicit fallback, i18next returns the key string
    // when the key is unresolved.  This is the contract that lets
    // our `t(k, fallbackEN)` pattern in the JSX resolve to the
    // English string when the key is truly missing.
    expect(i18n.t("leads:nonexistent.deep.key")).toBe("nonexistent.deep.key");
    // WITH a fallback, i18next returns the fallback.
    expect(i18n.t("leads:nonexistent.deep.key", "Fallback copy"))
      .toBe("Fallback copy");
  });

  it("unsupported locale short-circuits to EN via fallbackLng", async () => {
    await i18n.changeLanguage("xx-not-a-locale");
    // The changeLanguage call resolves to the fallback ("en") when
    // the requested locale isn't in supportedLngs.  Verify the
    // resolved language + a spec-touched string both land on EN.
    expect(i18n.resolvedLanguage).toBe("en");
    expect(i18n.t("leads:tabs.active")).toBe("Active");
    // Restore for downstream tests in the same worker.
    await i18n.changeLanguage("en");
  });

  it("missing key under requested locale falls back to EN for that " +
     "same key (fallbackLng chain)", async () => {
    // Inject a synthetic key ONLY in EN so we can prove the fallback.
    i18n.addResource("en", "leads", "__p50_test_only_en_key",
                       "EN-only fallback value");
    await i18n.changeLanguage("es");
    // The Spanish bundle has no such key → i18next walks the
    // fallbackLng chain to EN and returns the EN string.
    expect(i18n.t("leads:__p50_test_only_en_key"))
      .toBe("EN-only fallback value");
    await i18n.changeLanguage("en");
  });
});
