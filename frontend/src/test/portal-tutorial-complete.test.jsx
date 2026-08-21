/**
 * Feb-2026 · P2 — ``markTutorialComplete()`` persistence helper.
 *
 * Small focused suite that verifies the exported helper fires the
 * right POST to the right endpoint, forwards an optional ``step``
 * argument, and never throws on transport failure (the OnboardingGate
 * contract keeps client-side dismiss even when the persistence call
 * fails — this is a nice-to-have layer, not a blocking gate).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...a) => postMock(...a), get: vi.fn(async () => ({})) },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u_customer", role: "customer" } }),
}));
vi.mock("@/theme", () => ({
  colors: { surface: "#fff", onSurface: "#000", muted: "#666",
             border: "#ccc", brand: "#0EA5E9" },
}));

import { markTutorialComplete } from "@/components/legal/OnboardingGate";

describe("OnboardingGate · markTutorialComplete", () => {
  beforeEach(() => { postMock.mockReset(); });

  it("POSTs to /customer-portal/tutorial/complete with an empty body when no step given", async () => {
    postMock.mockResolvedValue({
      tutorial_completed_at: "2026-05-01T09:00:00+00:00",
      already_completed: false,
    });
    const res = await markTutorialComplete();
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock).toHaveBeenCalledWith("/customer-portal/tutorial/complete", {});
    expect(res.already_completed).toBe(false);
  });

  it("forwards the optional ``step`` for future per-step granularity", async () => {
    postMock.mockResolvedValue({
      tutorial_completed_at: "2026-05-01T09:00:00+00:00",
      already_completed: false,
    });
    await markTutorialComplete("final");
    expect(postMock).toHaveBeenCalledWith("/customer-portal/tutorial/complete", { step: "final" });
  });

  it("swallows transport errors and returns null (client-side dismiss stays functional)", async () => {
    postMock.mockRejectedValue(new Error("network down"));
    const res = await markTutorialComplete();
    // Must NOT throw — this is a nice-to-have persistence layer.
    expect(res).toBeNull();
  });
});
