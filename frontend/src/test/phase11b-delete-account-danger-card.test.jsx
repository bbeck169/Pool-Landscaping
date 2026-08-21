/**
 * Feb-2026 · P11b — Delete-account danger card confirmation flow.
 *
 * Pins the two-step confirmation: the destructive button STAYS
 * disabled until the phrase ``DELETE`` is typed verbatim; only then
 * does clicking it fire ``DELETE /api/customer-portal/account``.
 *
 * Coverage:
 *   1. On mount, the initial open-button is rendered; no delete
 *      call fires just from mounting.
 *   2. After opening the confirmation, the destructive button is
 *      disabled while the phrase field is empty.
 *   3. Typing anything OTHER than ``DELETE`` keeps the button
 *      disabled (case sensitive — "delete" lowercase must not arm).
 *   4. Typing exactly ``DELETE`` arms the button; clicking it fires
 *      ``api.delete("/customer-portal/account")`` exactly once with
 *      the correct path.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Module mocks ──────────────────────────────────────────────
vi.mock("@/api", () => ({
  api: { delete: vi.fn(async () => ({ deleted: true, anonymized_at: "x" })) },
}));
vi.mock("@/auth", () => ({ useAuth: () => ({ logout: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", onSurface: "#111", muted: "#666",
    error: "#dc2626", brand: "#2563eb", background: "#fafafa",
    border: "#e5e7eb",
  },
}));

import DeleteAccountDangerCard from "@/components/portal/DeleteAccountDangerCard";
import { api } from "@/api";


function renderCard() {
  return render(
    <MemoryRouter>
      <DeleteAccountDangerCard />
    </MemoryRouter>,
  );
}


describe("DeleteAccountDangerCard (P11b · App Store item 3)", () => {
  beforeEach(() => {
    api.delete.mockClear();
  });

  it("does NOT fire a delete call just from mounting", () => {
    renderCard();
    expect(api.delete).not.toHaveBeenCalled();
  });

  it("shows the open-button before the confirm modal is opened", () => {
    const { getByTestId, queryByTestId } = renderCard();
    expect(getByTestId("portal-preferences-delete-account-open-btn")).toBeTruthy();
    expect(queryByTestId("portal-preferences-delete-account-confirm-btn")).toBeNull();
  });

  it("keeps the confirm button disabled while the phrase is empty or wrong", () => {
    const { getByTestId } = renderCard();
    fireEvent.click(getByTestId("portal-preferences-delete-account-open-btn"));
    const confirmBtn = getByTestId("portal-preferences-delete-account-confirm-btn");
    expect(confirmBtn.disabled).toBe(true);

    const input = getByTestId("portal-preferences-delete-account-phrase-input");
    // Case-sensitive: lowercase must NOT arm the button.
    fireEvent.change(input, { target: { value: "delete" } });
    expect(confirmBtn.disabled).toBe(true);

    fireEvent.change(input, { target: { value: "DELETE!" } });
    expect(confirmBtn.disabled).toBe(true);

    // Correct phrase enables the button.
    fireEvent.change(input, { target: { value: "DELETE" } });
    expect(confirmBtn.disabled).toBe(false);
  });

  it("fires DELETE /customer-portal/account exactly once when confirmed", async () => {
    const { getByTestId } = renderCard();
    fireEvent.click(getByTestId("portal-preferences-delete-account-open-btn"));
    fireEvent.change(
      getByTestId("portal-preferences-delete-account-phrase-input"),
      { target: { value: "DELETE" } },
    );
    fireEvent.click(getByTestId("portal-preferences-delete-account-confirm-btn"));
    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(api.delete).toHaveBeenCalledWith("/customer-portal/account");
  });
});
