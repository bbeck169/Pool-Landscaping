/**
 * Feb 2026 · OpsHub menu-route alias — ``/price-book`` → ``pricebook`` tab.
 *
 * The sidebar Pricebook link routes to ``/price-book`` (dashed, matches
 * the human-readable label). Internally, the OpsHub tab key is
 * ``pricebook`` (no dash). Without an alias, users clicking Pricebook
 * from the sidebar fell through to the default Dispatch tab.
 *
 * The pure resolver ``resolveOpsPathTab(pathname)`` is exported from
 * ``pages/ops/OpsHub.jsx`` so this spec can lock in the mapping
 * without mounting the full OpsHub tree (which pulls in dozens of
 * adjacent modules).
 */
import { describe, it, expect } from "vitest";
import {
  resolveOpsPathTab,
  OPS_KNOWN_SEGMENTS,
  OPS_SEGMENT_ALIASES,
} from "@/pages/ops/OpsHub";


describe("OpsHub · pathname → tab resolver", () => {
  it("registers `price-book` → `pricebook` in the alias map", () => {
    expect(OPS_SEGMENT_ALIASES["price-book"]).toBe("pricebook");
  });

  it("resolves `/price-book` (dashed) to the `pricebook` tab", () => {
    expect(resolveOpsPathTab("/price-book")).toBe("pricebook");
  });

  it("keeps resolving `/pricebook` (undashed) to the `pricebook` tab", () => {
    expect(resolveOpsPathTab("/pricebook")).toBe("pricebook");
  });

  it("passes through every KNOWN segment unchanged", () => {
    for (const seg of OPS_KNOWN_SEGMENTS) {
      expect(resolveOpsPathTab(`/${seg}`)).toBe(seg);
    }
  });

  it("returns `''` for unknown segments so the caller falls back to `dispatch`", () => {
    expect(resolveOpsPathTab("/customers")).toBe("");
    expect(resolveOpsPathTab("/nonsense")).toBe("");
  });

  it("returns `''` for an empty / null / root path", () => {
    expect(resolveOpsPathTab("")).toBe("");
    expect(resolveOpsPathTab("/")).toBe("");
    expect(resolveOpsPathTab(null)).toBe("");
  });

  it("only inspects the first path segment (extra segments ignored)", () => {
    expect(resolveOpsPathTab("/price-book/anything/else")).toBe("pricebook");
    expect(resolveOpsPathTab("/team/roster/detail")).toBe("team");
  });
});
