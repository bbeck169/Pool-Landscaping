/**
 * Phase H3 · Feb-2026 — useConfirmDelete hook migration + QB revoke.
 *
 * The hook already renders a real ``<ConfirmDeleteDialog>`` (not
 * ``window.confirm``) as of the Feb-2026 Item-1 follow-up. H3 adds:
 *
 *   1. A ``typedKeyword`` shorthand that maps onto the pre-existing
 *      ``requireTypeConfirm`` + ``typeConfirmString`` pair, so
 *      brief-spec call sites can pass one field instead of two.
 *   2. QB Revoke Connection migrated onto the hook with
 *      ``typedKeyword: "REVOKE"``.  The last ``window.confirm(``
 *      in ``QuickBooksIntegrationPage.jsx`` is gone.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const HOOK_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/hooks/useConfirmDelete.jsx"),
  "utf-8",
);
const QB_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
      "src/pages/admin/integrations/QuickBooksIntegrationPage.jsx"),
  "utf-8",
);


describe("H3 · useConfirmDelete typedKeyword alias", () => {
  it("hook renders a real dialog (not window.confirm)", () => {
    expect(HOOK_SRC).toMatch(/<ConfirmDeleteDialog/);
    // Strip line-comments before the window.confirm sweep so the
    // historical migration note in the header doesn't false-fire.
    const codeOnly = HOOK_SRC
      .split("\n")
      .filter((l) => !l.trim().startsWith("//"))
      .join("\n");
    expect(codeOnly).not.toMatch(/window\.confirm\(/);
  });

  it("hook normalises typedKeyword → {requireTypeConfirm, typeConfirmString}", () => {
    // The ask() body must translate the brief-spec alias into the
    // dialog's canonical two-flag shape.
    expect(HOOK_SRC).toMatch(/typedKeyword/);
    expect(HOOK_SRC).toMatch(
      /normalised\.requireTypeConfirm\s*=\s*true/,
    );
    expect(HOOK_SRC).toMatch(
      /normalised\.typeConfirmString\s*=\s*opts\.typedKeyword/,
    );
  });

  it("hook preserves the Promise<boolean> return shape", () => {
    // The ask() callback must still return a Promise the caller
    // ``await``s (existing 3 call sites depend on this).
    expect(HOOK_SRC).toMatch(/return new Promise\(\(resolve\) =>/);
  });
});


describe("H3 · QB Revoke Connection migrated onto the hook", () => {
  it("imports useConfirmDelete", () => {
    expect(QB_SRC).toMatch(
      /import useConfirmDelete from "@\/hooks\/useConfirmDelete"/,
    );
  });

  it("revoke handler uses askRevoke with typedKeyword=REVOKE", () => {
    // Locate the revoke closure inside ConnectTab and assert the
    // hook wire.
    const idx = QB_SRC.indexOf("const revoke = async (id) => {");
    expect(idx).toBeGreaterThan(-1);
    const body = QB_SRC.slice(idx, idx + 900);
    expect(body).toMatch(/askRevoke\(\{/);
    expect(body).toMatch(/typedKeyword:\s*"REVOKE"/);
    expect(body).not.toMatch(/window\.confirm\(/);
  });

  it("mounts the dialog inside ConnectTab so it renders in the tree", () => {
    // ``{revokeDialog}`` must appear inside JSX so React actually
    // paints the modal when ``askRevoke`` opens it.
    expect(QB_SRC).toMatch(/\{revokeDialog\}/);
  });

  it("preserves the DELETE call and toast handling", () => {
    // Guard against an accidental delete-of-side-effect refactor.
    expect(QB_SRC).toMatch(
      /fetch\(`\$\{API\}\/qbo\/connections\/\$\{id\}`,\s*\{\s*method:\s*"DELETE"/,
    );
    expect(QB_SRC).toMatch(/toast\.success\("Connection revoked/);
    expect(QB_SRC).toMatch(/toast\.error\("Revoke failed/);
  });
});


describe("H3 · regression guards for pre-existing hook callers", () => {
  it("hook keeps backward-compat with requireTypeConfirm + typeConfirmString", () => {
    // The 3 pre-existing callers (CustomerDetail, VanitySlugsPage,
    // AIBrainPage) pass the two-flag shape; the dialog wire must
    // still forward those explicit fields verbatim.
    expect(HOOK_SRC).toMatch(
      /requireTypeConfirm=\{!!state\.requireTypeConfirm\}/,
    );
    expect(HOOK_SRC).toMatch(
      /typeConfirmString=\{state\.typeConfirmString \|\| "DELETE"\}/,
    );
  });
});
