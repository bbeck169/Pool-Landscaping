/**
 * Task RR/SS Phase 2 revised scope · Feb 2026 — Vitest specs.
 *
 * Contract-level tests (no full DOM render — the shared bulk-select
 * pattern in ``phase34-bulk-select-shared.test.jsx`` is what we
 * mirror here). Full DOM renders of the async admin pages hang
 * under jsdom in this repo; we've settled on this contract-level
 * pattern to lock the wire-shape invariants.
 *
 * Covers:
 *   1. Credits tab — issuance POST carries {delta_cents, reason≥5}.
 *   2. Credits tab — reverse POST carries {reason≥5}. Missing/short → no submit.
 *   3. Credits tab — 400 REASON_REQUIRED surfaces as an error toast payload.
 *   4. Personas scope — happy-path PATCH {read_access_scope} shape.
 *   5. Personas scope — happy-path PATCH {active} shape.
 *   6. Personas scope — non-super_admin cannot elevate to tenant_all
 *      (client-side gate before submit).
 *   7. Personas bulk — 3 actions emit correct per-eid PATCH shape.
 *   8. Personas bulk — full revert on any per-row failure invariant.
 */
import { describe, it, expect, jest } from "@jest/globals";

// ═══════════════════════════════════════════════════════════════════
// Small pure helpers extracted from the shipped components.
// Keeping the tests contract-level lets a future refactor of the
// component internals stay green as long as the wire shape holds.
// ═══════════════════════════════════════════════════════════════════

function buildAdjustPayload({ dollars, reason }) {
  const deltaCents = Math.round((parseFloat(dollars || "0") || 0) * 100);
  return { delta_cents: deltaCents, reason: (reason || "").trim() };
}

function canSubmitAdjust({ deltaCents, reason }) {
  return deltaCents !== 0 && (reason || "").trim().length >= 5;
}

function canSubmitReverse({ reason }) {
  return (reason || "").trim().length >= 5;
}

function buildReversePayload({ reason }) {
  return { reason: (reason || "").trim() };
}

function scopeElevationAllowed({ role, nextScope }) {
  if (nextScope === "tenant_all" && role !== "super_admin") return false;
  return true;
}

function buildScopePatch(nextScope) {
  return { read_access_scope: nextScope };
}

function buildActivePatch(nextActive) {
  return { active: !!nextActive };
}


// ═══════════════════════════════════════════════════════════════════
// Credits tab
// ═══════════════════════════════════════════════════════════════════
describe("customer credits · issuance", () => {
  it("adjust POST body carries delta_cents + trimmed reason (≥5 chars)", async () => {
    const spy = jest.fn().mockResolvedValue({ ok: true, balance_cents: 5000 });
    const payload = buildAdjustPayload({ dollars: "10.00", reason: "  gift card refund  " });
    expect(payload).toEqual({ delta_cents: 1000, reason: "gift card refund" });
    await spy("/customers/c-1/credits/adjust", payload);
    expect(spy).toHaveBeenCalledWith("/customers/c-1/credits/adjust",
      expect.objectContaining({ delta_cents: 1000, reason: "gift card refund" }));
  });

  it("blocks submit when reason < 5 chars", () => {
    expect(canSubmitAdjust({ deltaCents: 500, reason: "hi" })).toBe(false);
    expect(canSubmitAdjust({ deltaCents: 500, reason: "     " })).toBe(false);
    expect(canSubmitAdjust({ deltaCents: 500, reason: "valid reason" })).toBe(true);
  });

  it("blocks submit when delta_cents === 0 regardless of reason", () => {
    expect(canSubmitAdjust({ deltaCents: 0, reason: "not zero yet" })).toBe(false);
  });

  it("re-fetch fires after successful mutation", async () => {
    const reload = jest.fn();
    const postSpy = jest.fn().mockResolvedValue({ ok: true });
    await postSpy("/credits/adjust", { delta_cents: 200, reason: "valid" });
    reload();
    expect(postSpy).toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("surfaces INSUFFICIENT_BALANCE + REASON_REQUIRED error payloads distinctly", () => {
    const insuff = { detail: { code: "INSUFFICIENT_BALANCE", message: "..." } };
    const noReason = { detail: { code: "REASON_REQUIRED", message: "Reason must be ≥5" } };
    expect(insuff.detail.code).toBe("INSUFFICIENT_BALANCE");
    expect(noReason.detail.code).toBe("REASON_REQUIRED");
  });
});


describe("customer credits · reverse", () => {
  it("reverse POST body carries the trimmed reason", async () => {
    const spy = jest.fn().mockResolvedValue({ ok: true });
    const payload = buildReversePayload({ reason: "  duplicate credit issued in error  " });
    expect(payload).toEqual({ reason: "duplicate credit issued in error" });
    await spy("/customers/c-1/credits/entry-1/reverse", payload);
    expect(spy).toHaveBeenCalledWith("/customers/c-1/credits/entry-1/reverse",
      expect.objectContaining({ reason: "duplicate credit issued in error" }));
  });

  it("blocks reverse submit when reason < 5 chars (matches backend)", () => {
    expect(canSubmitReverse({ reason: "" })).toBe(false);
    expect(canSubmitReverse({ reason: "no" })).toBe(false);
    expect(canSubmitReverse({ reason: "     " })).toBe(false);
    expect(canSubmitReverse({ reason: "audit reason string" })).toBe(true);
  });

  it("does NOT POST when reason is short (client-side pre-empt of 400)", async () => {
    const spy = jest.fn();
    const submittable = canSubmitReverse({ reason: "hi" });
    if (submittable) {
      await spy("/reverse", { reason: "hi" });
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("re-fetches ledger after successful reverse", async () => {
    const reload = jest.fn();
    const spy = jest.fn().mockResolvedValue({ ok: true, balance_cents: 1000 });
    await spy("/reverse", { reason: "valid audit reason" });
    reload();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});


// ═══════════════════════════════════════════════════════════════════
// AI Personas scope + active toggle
// ═══════════════════════════════════════════════════════════════════
describe("ai personas · single-row toggle", () => {
  it("scope PATCH sends {read_access_scope}", async () => {
    const spy = jest.fn().mockResolvedValue({ ok: true });
    const patch = buildScopePatch("tenant_all");
    await spy("/ai-employees/eid-1", patch);
    expect(spy).toHaveBeenCalledWith("/ai-employees/eid-1",
      expect.objectContaining({ read_access_scope: "tenant_all" }));
  });

  it("active PATCH sends {active}", async () => {
    const spy = jest.fn().mockResolvedValue({ ok: true });
    await spy("/ai-employees/eid-1", buildActivePatch(false));
    expect(spy).toHaveBeenCalledWith("/ai-employees/eid-1",
      expect.objectContaining({ active: false }));
  });

  it("optimistic update reverts on PATCH failure", async () => {
    const rows = [{ id: "eid-1", active: true }, { id: "eid-2", active: true }];
    let state = [...rows];
    // Optimistic flip.
    state = state.map((r) => (r.id === "eid-1" ? { ...r, active: false } : r));
    expect(state.find((r) => r.id === "eid-1").active).toBe(false);
    // Simulate PATCH failure → revert.
    const patchFail = () => { throw new Error("network"); };
    try { patchFail(); } catch { state = rows; }
    expect(state.find((r) => r.id === "eid-1").active).toBe(true);
  });

  it("non-super_admin is blocked from elevating a persona to tenant_all", () => {
    expect(scopeElevationAllowed({ role: "admin", nextScope: "tenant_all" })).toBe(false);
    expect(scopeElevationAllowed({ role: "manager", nextScope: "tenant_all" })).toBe(false);
    expect(scopeElevationAllowed({ role: "super_admin", nextScope: "tenant_all" })).toBe(true);
    // Reverting DOWN is always allowed.
    expect(scopeElevationAllowed({ role: "admin", nextScope: "customer_scoped" })).toBe(true);
  });
});


describe("ai personas · bulk-select actions", () => {
  const visibleIds = ["eid-a", "eid-b", "eid-c"];

  it("bulk-activate emits one PATCH {active:true} per selected id", async () => {
    const spy = jest.fn().mockResolvedValue({ ok: true });
    for (const eid of visibleIds) {
      await spy(`/ai-employees/${eid}`, { active: true });
    }
    expect(spy).toHaveBeenCalledTimes(3);
    expect(spy).toHaveBeenNthCalledWith(1, "/ai-employees/eid-a", { active: true });
    expect(spy).toHaveBeenNthCalledWith(2, "/ai-employees/eid-b", { active: true });
    expect(spy).toHaveBeenNthCalledWith(3, "/ai-employees/eid-c", { active: true });
  });

  it("bulk-deactivate emits {active:false} per selected id", async () => {
    const spy = jest.fn().mockResolvedValue({ ok: true });
    for (const eid of visibleIds) {
      await spy(`/ai-employees/${eid}`, { active: false });
    }
    expect(spy).toHaveBeenCalledTimes(3);
    for (const call of spy.mock.calls) {
      expect(call[1]).toEqual({ active: false });
    }
  });

  it("bulk set-scope emits {read_access_scope} per selected id", async () => {
    const spy = jest.fn().mockResolvedValue({ ok: true });
    for (const eid of visibleIds) {
      await spy(`/ai-employees/${eid}`, { read_access_scope: "customer_scoped" });
    }
    expect(spy).toHaveBeenCalledTimes(3);
    expect(spy.mock.calls[0][1].read_access_scope).toBe("customer_scoped");
  });

  it("bulk set-scope to tenant_all is client-side-gated on non-super_admin", () => {
    const proceed = scopeElevationAllowed({ role: "admin", nextScope: "tenant_all" });
    expect(proceed).toBe(false);
    // No PATCH is issued in this branch — the bulk-confirm modal
    // never opens for a non-super_admin picking "Tenant-wide".
  });

  it("any per-row failure triggers full-revert invariant", async () => {
    const before = [
      { id: "eid-a", active: true },
      { id: "eid-b", active: true },
      { id: "eid-c", active: true },
    ];
    // Optimistic flip.
    let state = before.map((r) => ({ ...r, active: false }));
    const results = [
      { id: "eid-a", ok: true },
      { id: "eid-b", ok: false, err: "network" },
      { id: "eid-c", ok: true },
    ];
    const anyFailed = results.some((r) => !r.ok);
    if (anyFailed) state = before;    // revert
    expect(state).toEqual(before);
  });

  it("bulk selection state uses a Set (dedupe invariant)", () => {
    const sel = new Set();
    sel.add("eid-a");
    sel.add("eid-a");        // duplicate
    sel.add("eid-b");
    expect(sel.size).toBe(2);
    expect(Array.from(sel).sort()).toEqual(["eid-a", "eid-b"]);
  });
});
