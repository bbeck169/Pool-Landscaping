/**
 * Phase 10 · Feb-2026 — Technician pay rates edit modal + kebab
 * menu integration tests.
 *
 * Mix of unit tests on ``TechnicianPayRatesModal`` and source-body
 * checks against ``OpsHub.jsx`` for the kebab wire-up. The full
 * TeamRoster is heavy to mount in isolation (its dep graph pulls
 * most of OpsHub) — static grep locks the role-gate + menu entry
 * contract per the ``customers-list-*`` convention.
 *
 * Cases:
 *   1. Modal renders both decimal inputs with inline help text.
 *   2. Decimal input accepts "25.50" without truncation.
 *   3. Save PATCHes ``/users/{id}`` with the exact string payload.
 *   4. Empty inputs persist as ``null`` (compute path treats as 0).
 *   5. Modal hydrates existing rates when target has them set.
 *   6. OpsHub.jsx kebab menu renders a Pay-Rates button for admins.
 *   7. Non-admins (manager / technician) do NOT see the Pay-Rates
 *      button — role-gated via ``canEditPay`` passed down to the
 *      kebab.
 *   8. OpsHub.jsx imports the modal under a stable path (so Phase
 *      11 / Phase 12 can grep).
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";

const OPS_HUB_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/ops/OpsHub.jsx"),
  "utf-8",
);


let apiPatchImpl = vi.fn();
vi.mock("@/api", () => ({
  api: { patch: (...a) => apiPatchImpl(...a), get: vi.fn() },
}));


import TechnicianPayRatesModal
  from "@/components/team/TechnicianPayRatesModal";


describe("Phase 10 · TechnicianPayRatesModal", () => {
  beforeEach(() => {
    apiPatchImpl = vi.fn().mockResolvedValue({});
  });
  afterEach(() => cleanup());

  const _TARGET = {
    id: "u-1",
    name: "Taylor Tech",
    email: "taylor@test.local",
    hourly_rate: null,
    per_pool_rate: null,
  };

  it("1. Renders both inputs with inline help text", () => {
    render(
      <TechnicianPayRatesModal
        target={_TARGET}
        onClose={() => {}}
        onSaved={() => {}}
        onError={() => {}}
      />,
    );
    expect(screen.getByTestId("tech-pay-rates-modal")).toBeTruthy();
    expect(screen.getByTestId("tech-pay-rate-hourly-input")).toBeTruthy();
    expect(screen.getByTestId("tech-pay-rate-per-pool-input")).toBeTruthy();
    // Inline semantic help text present per the brief.
    expect(screen.getByText(/Paid per hour of timecard activity/i))
      .toBeTruthy();
    expect(screen.getByText(/Flat dollar amount per completed pool/i))
      .toBeTruthy();
  });

  it("2. Decimal input accepts 25.50 without truncation", async () => {
    render(
      <TechnicianPayRatesModal
        target={_TARGET}
        onClose={() => {}}
        onSaved={() => {}}
        onError={() => {}}
      />,
    );
    const hourly = screen.getByTestId("tech-pay-rate-hourly-input");
    fireEvent.change(hourly, { target: { value: "25.50" } });
    expect(hourly.value).toBe("25.50");
  });

  it("3. Save PATCHes /users/{id} with the string decimal payload", async () => {
    const onSaved = vi.fn();
    render(
      <TechnicianPayRatesModal
        target={_TARGET}
        onClose={() => {}}
        onSaved={onSaved}
        onError={() => {}}
      />,
    );
    fireEvent.change(screen.getByTestId("tech-pay-rate-hourly-input"), {
      target: { value: "25.50" },
    });
    fireEvent.change(screen.getByTestId("tech-pay-rate-per-pool-input"), {
      target: { value: "10.00" },
    });
    fireEvent.click(screen.getByTestId("tech-pay-rates-save-btn"));
    await waitFor(() => expect(apiPatchImpl).toHaveBeenCalled());

    const [url, body] = apiPatchImpl.mock.calls[0];
    expect(url).toBe("/users/u-1");
    expect(body).toEqual({
      hourly_rate: "25.50",
      per_pool_rate: "10.00",
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("4. Empty inputs persist as null (compute treats as 0)", async () => {
    render(
      <TechnicianPayRatesModal
        target={_TARGET}
        onClose={() => {}}
        onSaved={() => {}}
        onError={() => {}}
      />,
    );
    // Leave both inputs empty, click save.
    fireEvent.click(screen.getByTestId("tech-pay-rates-save-btn"));
    await waitFor(() => expect(apiPatchImpl).toHaveBeenCalled());
    const [, body] = apiPatchImpl.mock.calls[0];
    expect(body).toEqual({
      hourly_rate: null,
      per_pool_rate: null,
    });
  });

  it("5. Modal hydrates existing rates from the target doc", () => {
    render(
      <TechnicianPayRatesModal
        target={{ ..._TARGET, hourly_rate: "22.00", per_pool_rate: "8.00" }}
        onClose={() => {}}
        onSaved={() => {}}
        onError={() => {}}
      />,
    );
    expect(screen.getByTestId("tech-pay-rate-hourly-input").value).toBe("22.00");
    expect(screen.getByTestId("tech-pay-rate-per-pool-input").value).toBe("8.00");
  });
});


describe("Phase 10 · OpsHub TeamRoster kebab + modal wire-up", () => {
  it("6. OpsHub.jsx imports TechnicianPayRatesModal", () => {
    // Stable import path — Phase 11 may grep for it to add a bulk
    // apply flow next to the per-row edit.
    expect(OPS_HUB_SRC).toMatch(
      /import\s+TechnicianPayRatesModal\s+from\s+"@\/components\/team\/TechnicianPayRatesModal"/,
    );
  });

  it("7. TeamRoster passes canEditPay (admin-gated) to the kebab", () => {
    // Admin / super_admin only — the perm matrix for Phase 10. The
    // flag mirrors the existing ``canReset`` / ``canDelete`` idiom.
    expect(OPS_HUB_SRC).toMatch(/canEditPay/);
    // The kebab receives the flag + the onEditPay handler.
    expect(OPS_HUB_SRC).toMatch(/onEditPay=\{/);
  });

  it("8. Kebab renders a Pay-Rates button only when canEditPay is true", () => {
    // Static grep — the menu-item block is gated behind
    // ``canEditPay`` just like the existing reset/delete items.
    expect(OPS_HUB_SRC).toMatch(
      /\{canEditPay\s*\?\s*\(/,
    );
    expect(OPS_HUB_SRC).toMatch(
      /data-testid=\{`team-row-edit-pay-btn-\$\{row\.id\}`\}/,
    );
  });

  it("9. Modal is wired into TeamRoster via payEditTarget state", () => {
    // The parent holds the open-dialog target (same pattern as
    // resetTarget / deleteTarget / hardDeleteTarget).
    expect(OPS_HUB_SRC).toMatch(/payEditTarget/);
    expect(OPS_HUB_SRC).toMatch(/setPayEditTarget/);
  });
});
