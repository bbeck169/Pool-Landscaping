/**
 * Phase 54d · Feb-2026 — Wholesale supplier metadata map.
 *
 * Single source of truth for per-supplier copy on the settings page.
 * Adding a new supplier in future phases (54e / 54f / etc.) is a
 * config patch here + wiring the backend connector — no changes to
 * ``SupplierSettings.jsx``.
 *
 * Shape:
 *   - Wired suppliers: full entry with tagline, labels, placeholders,
 *     delete-confirm copy. NO ``coming_in`` key.
 *   - Unwired suppliers: minimal entry with ``display_name``,
 *     ``tagline``, and ``coming_in`` (phase label).
 *
 * The vitest source-inspection test in
 * ``src/test/supplier-settings-metadata.test.jsx`` asserts every slug
 * in ``WIRED_SLUGS`` has a full entry (no ``coming_in`` stub) so we
 * catch a wire-up-without-metadata regression at test time.
 */
export const SUPPLIER_METADATA = {
  poolcorp: {
    display_name:         "Pool360 (PoolCorp)",
    tagline:              "Live wholesale pricebook sync (Playwright headless).",
    username_label:       "Pool360 username",
    username_placeholder: "your-pool360-username",
    password_label:       "Password",
    password_placeholder: "your-pool360-password",
    delete_confirm_text:  "Remove saved Pool360 credentials? Syncs will stop working until new credentials are provided.",
    sync_description:     "Pool360 catalog import — pool + spa equipment.",
  },
  siteone: {
    display_name:         "SiteOne",
    tagline:              "SiteOne B2B pricebook sync (Playwright headless).",
    username_label:       "SiteOne username",
    username_placeholder: "your-siteone-username",
    password_label:       "Password",
    password_placeholder: "your-siteone-password",
    delete_confirm_text:  "Remove saved SiteOne credentials? Syncs will stop working until new credentials are provided.",
    sync_description:     "SiteOne catalog import — landscaping supplies + irrigation.",
  },
  ewing: {
    display_name:         "Ewing Irrigation",
    tagline:              "Ewing Irrigation B2B pricebook sync (Playwright headless).",
    username_label:       "Ewing username",
    username_placeholder: "your-ewing-username",
    password_label:       "Password",
    password_placeholder: "your-ewing-password",
    delete_confirm_text:  "Remove saved Ewing credentials? Syncs will stop working until new credentials are provided.",
    sync_description:     "Ewing catalog import — irrigation + outdoor lighting + hardscape.",
  },
  heritage: {
    display_name:         "Heritage Pool Plus",
    tagline:              "Heritage Pool Plus wholesale pricebook sync (Playwright headless).",
    username_label:       "Heritage username",
    username_placeholder: "your-heritage-username",
    password_label:       "Password",
    password_placeholder: "your-heritage-password",
    delete_confirm_text:  "Remove saved Heritage Pool Plus credentials? Syncs will stop working until new credentials are provided.",
    sync_description:     "Heritage Pool Plus catalog import — pool equipment + chemicals.",
  },
  epoolsupply: {
    display_name:         "ePoolSupply",
    tagline:              "ePoolSupply wholesale pricebook sync (Playwright headless).",
    username_label:       "ePoolSupply username",
    username_placeholder: "your-epoolsupply-username",
    password_label:       "Password",
    password_placeholder: "your-epoolsupply-password",
    delete_confirm_text:  "Remove saved ePoolSupply credentials? Syncs will stop working until new credentials are provided.",
    sync_description:     "ePoolSupply catalog import — pool + spa equipment.",
  },
};

// Slugs whose entries carry the full wired shape. Kept in sync with
// the backend's ``_WIRED_SYNC_SLUGS`` set in ``routers/suppliers.py``.
export const WIRED_SLUGS = new Set(
  Object.keys(SUPPLIER_METADATA).filter(
    (slug) => !SUPPLIER_METADATA[slug].coming_in,
  ),
);
