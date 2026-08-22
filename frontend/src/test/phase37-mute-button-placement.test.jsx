/**
 * Feb-2026 · P37-UX — CustomersList "Mark Muted / Unmute" button
 * placement.
 *
 * Product ask: consolidate row-level action buttons on the far right.
 *
 *   - Active tab   → MuteControl pill sits INSIDE the actions cell,
 *                    as a sibling of the "Mark inactive" button.
 *   - Inactive tab → MuteControl pill sits INSIDE the actions cell,
 *                    as a sibling of the "Reactivate" button.
 *   - Muted tab    → REGRESSION PIN: MuteControl stays inline with
 *                    the row's status chips (name column). It must
 *                    NOT jump into the actions cell there so the
 *                    Unmute affordance stays glued to the MUTED
 *                    badge in the auditing surface.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Mocks ────────────────────────────────────────────────────────────
let currentRole = "admin";

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: currentRole,
    effectiveRole: currentRole,
    isAdmin: currentRole === "admin" || currentRole === "super_admin",
    isAdminOrManager:
      currentRole === "admin" || currentRole === "super_admin"
      || currentRole === "manager",
    canDo: () => true,
  }),
}));

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(),
  }),
}));


import CustomersList from "@/pages/customers/CustomersList";


function _mount(role = "admin") {
  currentRole = role;
  return render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


function _installGetRouter({ active = [], inactive = [], muted = [] } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/customer-tags")) return Promise.resolve({ items: [] });
    if (path.includes("count_only=true")) {
      if (path.includes("is_muted=true")) return Promise.resolve({ count: muted.length });
      if (path.includes("is_active=true")) return Promise.resolve({ count: active.length });
      if (path.includes("is_active=false")) return Promise.resolve({ count: inactive.length });
      return Promise.resolve({ count: 0 });
    }
    if (path.includes("is_muted=true")) return Promise.resolve(muted);
    if (path.includes("is_active=false")) return Promise.resolve(inactive);
    if (path.startsWith("/customers")) return Promise.resolve(active);
    return Promise.resolve({});
  });
}


beforeEach(() => {
  mockGet.mockClear();
});


describe("CustomersList · P37-UX mute-button placement", () => {
  it("Active tab: Mark Muted pill sits next to 'Mark inactive' inside the actions cell", async () => {
    _installGetRouter({
      active: [
        { id: "c-active-1", name: "Active Al", is_active: true, is_muted: false },
      ],
    });
    _mount("admin");

    await waitFor(() =>
      expect(screen.getByTestId("customer-row-c-active-1")).toBeTruthy());

    const muteBtn = await screen.findByTestId("mute-control-btn-c-active-1");
    const inactiveBtn = screen.getByTestId("row-c-active-1-deactivate");

    // Both buttons must live inside the same flex action-cluster
    // (the last <td>'s <div class="flex ... justify-end">).
    const actionCluster = inactiveBtn.parentElement;
    expect(actionCluster.className).toMatch(/justify-end/);
    expect(actionCluster.contains(muteBtn)).toBe(true);

    // Sanity: they're immediate siblings (no wrapper between them).
    expect(muteBtn.parentElement).toBe(actionCluster);
  });

  it("Inactive tab: Mark Muted pill sits next to 'Reactivate' inside the actions cell", async () => {
    _installGetRouter({
      active: [{ id: "c-active-1", name: "Active Al", is_active: true }],
      inactive: [
        { id: "c-inact-1", name: "Inactive Ida", is_active: false, is_muted: false },
      ],
    });
    _mount("admin");

    // Switch to Inactive tab.
    await waitFor(() => expect(screen.getByTestId("tab-inactive")).toBeTruthy());
    fireEvent.click(screen.getByTestId("tab-inactive"));

    await waitFor(() =>
      expect(screen.getByTestId("customer-row-c-inact-1")).toBeTruthy());

    const muteBtn = await screen.findByTestId("mute-control-btn-c-inact-1");
    const reactivateBtn = screen.getByTestId("row-c-inact-1-reactivate");

    const actionCluster = reactivateBtn.parentElement;
    expect(actionCluster.className).toMatch(/justify-end/);
    expect(actionCluster.contains(muteBtn)).toBe(true);
    expect(muteBtn.parentElement).toBe(actionCluster);
  });

  it("Muted tab regression: Unmute pill stays inline with the MUTED badge (NOT in the actions cell)", async () => {
    const one_hour_ago = new Date(Date.now() - 3600_000).toISOString();
    _installGetRouter({
      muted: [
        { id: "c-mute-1", name: "Muted Mel", is_active: true,
          is_muted: true, muted_at: one_hour_ago },
      ],
    });
    _mount("admin");

    await waitFor(() => expect(screen.getByTestId("tab-muted")).toBeTruthy());
    fireEvent.click(screen.getByTestId("tab-muted"));

    await waitFor(() =>
      expect(screen.getByTestId("customer-row-c-mute-1")).toBeTruthy());

    const muteBtn = await screen.findByTestId("mute-control-btn-c-mute-1");
    const mutedBadge = screen.getByTestId("muted-badge-c-mute-1");

    // The pill must be a sibling of the row's status-chip cluster —
    // i.e. share a parent with the MUTED badge — and must NOT be
    // inside the right-aligned action cluster (justify-end).
    expect(muteBtn.parentElement).toBe(mutedBadge.parentElement);
    expect(muteBtn.parentElement.className || "").not.toMatch(/justify-end/);

    // And the row's Mark-inactive / Reactivate cluster (if any) must
    // NOT contain the mute pill on this tab. Muted-tab rows have
    // is_active=true → the "Mark inactive" button is present.
    const inactiveBtn = screen.queryByTestId("row-c-mute-1-deactivate");
    if (inactiveBtn) {
      const cluster = inactiveBtn.parentElement;
      expect(cluster.contains(muteBtn)).toBe(false);
    }
  });
});
