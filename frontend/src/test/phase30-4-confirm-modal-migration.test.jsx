/**
 * Phase 30.4 · Feb-2026 — destructive Alert.alert → ConfirmModal migration.
 *
 * Motivating cause: native ``Alert.alert(...)`` silently no-ops on some
 * Android/Expo Go builds (root cause of the Phase 30.3 portal sign-out
 * P0). Every user-choice DESTRUCTIVE confirmation on mobile has been
 * migrated to a shared ``<ConfirmModal>`` primitive + ``showConfirm()``
 * imperative API mounted once at the app root.
 *
 * This suite locks:
 *   1. ``ConfirmModal`` module exports the expected surface
 *      (component, hook, host, imperative function, types).
 *   2. ``mobile/app/_layout.tsx`` mounts ``<ConfirmModalHost />`` once.
 *   3. Every migrated site imports ``showConfirm`` from
 *      ``@/src/components/ConfirmModal`` and no longer contains a
 *      destructive ``Alert.alert`` block.
 *   4. Portal-home sign-out (fixed in Phase 30.3) stays Alert-free —
 *      regression guard against a re-introduction here.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, "../../..", p), "utf-8");

const MIGRATED_SITES = [
  // (file, expected confirm-modal title, whether it uses showConfirm)
  ["mobile/src/components/tools/GlobalMenu.tsx", "Log out?", "inline"],
  ["mobile/src/components/files/FileList.tsx", "Delete File", "showConfirm"],
  ["mobile/src/components/media/VideoMediaUploader.tsx", "Delete video?", "showConfirm"],
  ["mobile/src/components/customers/CustomerEquipmentLibrary.tsx", "Delete photo?", "showConfirm"],
  ["mobile/app/landscape.tsx", "Delete design?", "showConfirm"],
  ["mobile/app/payments/methods.tsx", "Remove card?", "showConfirm"],
  ["mobile/app/income-categories.tsx", "Remove category", "showConfirm"],
  // Feb-2026 · K55.a — SuperCool integration page removed as part
  // of the sunset (PHASE_K55_a_FRONTEND_REMOVAL.md).  This entry
  // used to lock in ``mobile/app/settings/integrations/supercool.tsx``
  // ``Disconnect Supercool?`` confirmation dialog — no longer
  // applicable.
  ["mobile/app/settings/vanity-slugs.tsx", "Delete alias?", "showConfirm"],
  ["mobile/app/admin/seo/llm-visibility.tsx", "Delete query", "showConfirm"],
  ["mobile/app/aeo/library.tsx", "Delete template?", "showConfirm"],
  ["mobile/app/marketing/content-studio.tsx", "Delete image?", "showConfirm"],
  ["mobile/app/estimator/templates.tsx", "Delete template", "showConfirm"],
  ["mobile/app/(app)/templates/index.tsx", "Delete Template", "showConfirm"],
  ["mobile/app/(app)/templates/[id].tsx", "Delete this template?", "showConfirm"],
  ["mobile/app/(app)/schedule/calendar.tsx", "Delete", "showConfirm"], // template-literal title starts with "Delete"
];

describe("Phase 30.4 · ConfirmModal primitive", () => {
  const src = R("mobile/src/components/ConfirmModal.tsx");

  it("exports the declarative <ConfirmModal /> component", () => {
    expect(src).toMatch(/export\s+function\s+ConfirmModal\s*\(/);
    expect(src).toMatch(/export\s+type\s+ConfirmModalProps/);
  });

  it("exports the useConfirm() hook", () => {
    expect(src).toMatch(/export\s+function\s+useConfirm\s*\(/);
  });

  it("exports the imperative showConfirm() and ConfirmModalHost", () => {
    expect(src).toMatch(/export\s+function\s+showConfirm\s*\(/);
    expect(src).toMatch(/export\s+function\s+ConfirmModalHost\s*\(/);
  });

  it("declares ConfirmOptions with destructive / primary styles", () => {
    expect(src).toMatch(/export\s+type\s+ConfirmStyle\s*=\s*["']destructive["']\s*\|\s*["']primary["']/);
    expect(src).toMatch(/onConfirm:\s*\(\)\s*=>\s*void\s*\|\s*Promise<void>/);
  });

  it("declares testIDs for the root, backdrop, cancel, confirm, and body", () => {
    expect(src).toMatch(/testID={testID\s*\|\|\s*"confirm-modal-root"}/);
    expect(src).toMatch(/testID="confirm-modal-backdrop"/);
    expect(src).toMatch(/testID="confirm-modal-cancel"/);
    expect(src).toMatch(/testID="confirm-modal-confirm"/);
    expect(src).toMatch(/testID="confirm-modal-title"/);
  });

  it("uses accessibilityRole='alert' on the modal card", () => {
    expect(src).toMatch(/accessibilityRole="alert"/);
  });

  it("uses colors.error for the destructive button and colors.brand for primary", () => {
    expect(src).toMatch(/backgroundColor:\s*colors\.error/);
    expect(src).toMatch(/backgroundColor:\s*colors\.brand/);
  });
});

describe("Phase 30.4 · root layout mounts <ConfirmModalHost />", () => {
  const layout = R("mobile/app/_layout.tsx");

  it("imports ConfirmModalHost from the shared module", () => {
    expect(layout).toMatch(
      /import\s+\{\s*ConfirmModalHost\s*\}\s+from\s+["']@\/src\/components\/ConfirmModal["']/,
    );
  });

  it("renders <ConfirmModalHost /> inside the provider tree", () => {
    expect(layout).toMatch(/<ConfirmModalHost\s*\/>/);
  });
});

describe("Phase 30.4 · destructive Alert.alert sites migrated", () => {
  for (const [file, expectedTitle, mode] of MIGRATED_SITES) {
    it(`${file} · migrated (${mode})`, () => {
      const contents = R(file);

      // Special case — GlobalMenu.tsx uses its own inline confirm UI.
      if (mode === "inline") {
        // No Alert.alert for the "Log out?" flow.
        expect(contents).not.toMatch(
          /Alert\.alert\(\s*["']Log out\?["']/,
        );
        // The inline confirm UI is still present.
        expect(contents).toMatch(/setConfirmingLogout\(true\)/);
        return;
      }

      // Every other site must import showConfirm.
      expect(contents).toMatch(
        /import\s+\{\s*showConfirm\s*\}\s+from\s+["']@\/src\/components\/ConfirmModal["']/,
      );
      // At least one showConfirm call.
      expect(contents).toMatch(/showConfirm\(\s*\{/);
      // And no more destructive Alert.alert blocks in this file.
      // Match ``style: "destructive"`` or ``style: 'destructive'`` as
      // the marker of a legacy destructive-Alert action row.
      expect(contents).not.toMatch(/style\s*:\s*["']destructive["']/);
      // The expected title survives verbatim (helps catch accidental
      // copy-changes during future refactors).
      expect(contents).toMatch(
        new RegExp(`title:\\s*[\`"'][^\`"']*${expectedTitle.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}`),
      );
    });
  }
});

describe("Phase 30.4 · regression guards", () => {
  const home = R("mobile/app/portal/home.tsx");

  it("portal home sign-out (Phase 30.3) still Alert-free in code", () => {
    // Strip line comments before matching so the historical breadcrumb
    // in home.tsx's comment paragraph does not falsely trip the guard.
    const codeOnly = home
      .split("\n")
      .filter((ln) => !/^\s*(?:\/\/|\*)/.test(ln))
      .join("\n");
    expect(codeOnly).not.toMatch(/Alert\.alert\(/);
  });

  it("portal home retains the direct handleSignOut wiring", () => {
    expect(home).toMatch(/onPress=\{handleSignOut\}/);
    expect(home).toMatch(/await\s+logout\(\)/);
    expect(home).toMatch(/router\.replace\(\s*["']\/login["']\s*\)/);
  });
});
