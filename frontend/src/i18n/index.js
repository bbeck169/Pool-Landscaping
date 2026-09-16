/**
 * Phase D3 · Feb 2026 — i18n scaffolding.
 *
 * Boots ``i18next`` with the three shipped locales (en / es / fr).
 * Loaded ONCE at app entry (``src/index.js``) before ``<App />``
 * mounts so the first render already sees the resolved locale.
 *
 * Resolution order:
 *   1. localStorage key ``lang`` (set by the language selector +
 *      the ``/api/users/me`` self-patch reflux)
 *   2. ``navigator.language``
 *   3. fallback ``en``
 *
 * Every locale bundles three namespaces:
 *   * ``common``      — shared UI atoms
 *   * ``industries``  — 23 canonical slugs → display names
 *   * ``checklist``   — industry-checklist form shell strings
 *
 * Row-level checklist template translations are Phase D4.
 * Email / SMS body translations are Phase D5.
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import enCommon from "./locales/en/common.json";
import enIndustries from "./locales/en/industries.json";
import enChecklist from "./locales/en/checklist.json";

import esCommon from "./locales/es/common.json";
import esIndustries from "./locales/es/industries.json";
import esChecklist from "./locales/es/checklist.json";

import frCommon from "./locales/fr/common.json";
import frIndustries from "./locales/fr/industries.json";
import frChecklist from "./locales/fr/checklist.json";


export const SUPPORTED_LOCALES = Object.freeze([
  { code: "en", name: "English",  nativeName: "English"  },
  { code: "es", name: "Spanish",  nativeName: "Español"  },
  { code: "fr", name: "French",   nativeName: "Français" },
]);


const resources = {
  en: { common: enCommon, industries: enIndustries, checklist: enChecklist },
  es: { common: esCommon, industries: esIndustries, checklist: esChecklist },
  fr: { common: frCommon, industries: frIndustries, checklist: frChecklist },
};


// Detector reads ``localStorage.lang`` first (set by the selector),
// falling back to the browser navigator. We deliberately DO NOT
// persist the detected value back to localStorage — the language
// selector is the single source of truth for that key.
const detector = new LanguageDetector();
detector.addDetector({
  name: "lang-localstorage",
  lookup() {
    try {
      const raw = (typeof window !== "undefined" && window.localStorage
        ? window.localStorage.getItem("lang")
        : "") || "";
      return raw ? String(raw).toLowerCase().slice(0, 2) : undefined;
    } catch { return undefined; }
  },
  cacheUserLanguage() { /* no-op — selector owns writes */ },
});


i18n
  .use(detector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "en",
    supportedLngs: ["en", "es", "fr"],
    ns: ["common", "industries", "checklist"],
    defaultNS: "common",
    detection: {
      order: ["lang-localstorage", "navigator"],
      caches: [],   // selector owns writes.
    },
    interpolation: { escapeValue: false },   // React already escapes.
    returnNull: false,
  });


export default i18n;
