/**
 * Phase M1 · Feb-2026 — Customer Merge Wizard vitest.
 *
 * Contract:
 *  * Search step filters primary + soft-deleted from results.
 *  * Conflict resolver renders 4 rows with default Primary radio.
 *  * Confirm step's MERGE text-gate keeps the destructive button
 *    disabled until "MERGE" is typed exactly.
 *  * Success POST fires with the right payload + toast + onMerged
 *    callback fires.
 *  * Non-admin doesn't see the trigger — asserted via CustomerDetail
 *    role-gate in a smaller companion test (this file focuses on
 *    the wizard component itself).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach }
       from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, act }
       from "@testing-library/react";


const apiGetMock = vi.fn();
const apiPostMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastInfo = vi.fn();


vi.mock("@/api", () => ({
  api: {
    get:  (...a) => apiGetMock(...a),
    post: (...a) => apiPostMock(...a),
  },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccess(...a),
    error:   (...a) => toastError(...a),
    info:    (...a) => toastInfo(...a),
    message: (...a) => toastInfo(...a),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7", borderStrong: "#D4D4D8",
    muted: "#71717A", onSurface: "#09090B",
    onSurfaceSecondary: "#52525B",
    brand: "#0284C7", error: "#DC2626", warning: "#CA8A04",
    onBrandPrimary: "#FFFFFF",
  },
}));


import CustomerMergeWizard
       from "@/pages/customers/CustomerMergeWizard";


const PRIMARY = {
  id: "cust-primary-1",
  name: "Alice Primary",
  email: "alice@ex.com",
  phone: "111-1111",
  address: "1 Primary St",
};

const DUPLICATE = {
  id: "cust-dupe-1",
  name: "Alicia Dupe",
  email: "alicia@ex.com",
  phone: "222-2222",
  address: "2 Dupe Ave",
};

const A_DELETED = {
  id: "cust-deleted-1",
  name: "Should Not Show",
  email: "gone@ex.com",
  is_deleted: true,
};


beforeEach(() => {
  apiGetMock.mockReset();
  apiPostMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  toastInfo.mockReset();
});
afterEach(() => cleanup());


describe("CustomerMergeWizard · M1 flow", () => {

  it("returns null when open=false", () => {
    const { container } = render(
      <CustomerMergeWizard open={false} primary={PRIMARY} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("Step 1 — search filters primary + soft-deleted from results",
    async () => {
      apiGetMock.mockResolvedValue({
        data: {
          items: [
            PRIMARY,      // must be filtered — same id as primary
            DUPLICATE,    // must stay
            A_DELETED,    // must be filtered — soft-deleted
          ],
        },
      });
      const onClose = vi.fn();
      render(
        <CustomerMergeWizard open={true} primary={PRIMARY}
                                onClose={onClose} />,
      );
      const input = screen.getByTestId("cmw-search-input");
      fireEvent.change(input, { target: { value: "ali" } });
      await waitFor(() => {
        expect(apiGetMock).toHaveBeenCalled();
      }, { timeout: 800 });
      await waitFor(() => {
        expect(
          screen.queryByTestId(`cmw-result-row-${DUPLICATE.id}`),
        ).toBeInTheDocument();
      });
      expect(
        screen.queryByTestId(`cmw-result-row-${PRIMARY.id}`),
      ).toBeNull();
      expect(
        screen.queryByTestId(`cmw-result-row-${A_DELETED.id}`),
      ).toBeNull();
    });

  it("Step 2 — resolver renders 4 rows with Primary radio default",
    async () => {
      apiGetMock.mockResolvedValue({ data: { items: [DUPLICATE] } });
      render(
        <CustomerMergeWizard open={true} primary={PRIMARY}
                                onClose={vi.fn()} />,
      );
      fireEvent.change(screen.getByTestId("cmw-search-input"),
                          { target: { value: "ali" } });
      await waitFor(() => screen.getByTestId(
        `cmw-select-${DUPLICATE.id}`));
      fireEvent.click(screen.getByTestId(
        `cmw-select-${DUPLICATE.id}`));
      await waitFor(() => screen.getByTestId("cmw-resolver"));
      for (const f of ["name", "email", "phone", "address"]) {
        const radioP = screen.getByTestId(`cmw-choice-${f}-primary`);
        expect(radioP.checked).toBe(true);
      }
    });

  it("Step 3 — MERGE-text gate keeps button disabled until typed",
    async () => {
      apiGetMock.mockResolvedValue({ data: { items: [DUPLICATE] } });
      render(
        <CustomerMergeWizard open={true} primary={PRIMARY}
                                onClose={vi.fn()} />,
      );
      fireEvent.change(screen.getByTestId("cmw-search-input"),
                          { target: { value: "ali" } });
      await waitFor(() => screen.getByTestId(
        `cmw-select-${DUPLICATE.id}`));
      fireEvent.click(screen.getByTestId(
        `cmw-select-${DUPLICATE.id}`));
      await waitFor(() => screen.getByTestId("cmw-resolver"));
      fireEvent.click(screen.getByTestId("cmw-next-btn"));
      await waitFor(() => screen.getByTestId("cmw-confirm"));
      const merge = screen.getByTestId("cmw-merge-btn");
      expect(merge.disabled).toBe(true);
      fireEvent.change(screen.getByTestId("cmw-confirm-input"),
                          { target: { value: "merge" } });
      expect(merge.disabled).toBe(true);  // case-sensitive
      fireEvent.change(screen.getByTestId("cmw-confirm-input"),
                          { target: { value: "MERGE" } });
      expect(merge.disabled).toBe(false);
    });

  it("Success — POST payload + toast + onMerged fire", async () => {
    apiGetMock.mockResolvedValue({ data: { items: [DUPLICATE] } });
    apiPostMock.mockResolvedValue({
      data: {
        ok: true,
        primary_customer_id:   PRIMARY.id,
        duplicate_customer_id: DUPLICATE.id,
        reparent_counts:      { jobs: 3, messages: 1 },
        merged_at: "2026-02-20T10:00:00Z",
      },
    });
    const onMerged = vi.fn();
    const onClose = vi.fn();
    render(
      <CustomerMergeWizard open={true} primary={PRIMARY}
                              onClose={onClose} onMerged={onMerged} />,
    );
    fireEvent.change(screen.getByTestId("cmw-search-input"),
                        { target: { value: "ali" } });
    await waitFor(() => screen.getByTestId(
      `cmw-select-${DUPLICATE.id}`));
    fireEvent.click(screen.getByTestId(
      `cmw-select-${DUPLICATE.id}`));
    await waitFor(() => screen.getByTestId("cmw-resolver"));
    // Flip phone to duplicate.
    fireEvent.click(screen.getByTestId("cmw-choice-phone-duplicate"));
    fireEvent.click(screen.getByTestId("cmw-next-btn"));
    await waitFor(() => screen.getByTestId("cmw-confirm"));
    fireEvent.change(screen.getByTestId("cmw-confirm-input"),
                        { target: { value: "MERGE" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("cmw-merge-btn"));
    });
    expect(apiPostMock).toHaveBeenCalledWith(
      "/customers/merge-wizard",
      expect.objectContaining({
        primary_customer_id:   PRIMARY.id,
        duplicate_customer_id: DUPLICATE.id,
        field_choices: expect.objectContaining({ phone: "duplicate" }),
      }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(onMerged).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Cross-tenant 403 → cross-tenant toast", async () => {
    apiGetMock.mockResolvedValue({ data: { items: [DUPLICATE] } });
    apiPostMock.mockRejectedValue({
      response: { status: 403,
                    data: { detail: "cross_tenant_merge_forbidden" } },
      message: "403",
    });
    render(
      <CustomerMergeWizard open={true} primary={PRIMARY}
                              onClose={vi.fn()} />,
    );
    fireEvent.change(screen.getByTestId("cmw-search-input"),
                        { target: { value: "ali" } });
    await waitFor(() => screen.getByTestId(
      `cmw-select-${DUPLICATE.id}`));
    fireEvent.click(screen.getByTestId(
      `cmw-select-${DUPLICATE.id}`));
    await waitFor(() => screen.getByTestId("cmw-resolver"));
    fireEvent.click(screen.getByTestId("cmw-next-btn"));
    await waitFor(() => screen.getByTestId("cmw-confirm"));
    fireEvent.change(screen.getByTestId("cmw-confirm-input"),
                        { target: { value: "MERGE" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("cmw-merge-btn"));
    });
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      expect.stringContaining("Cross-tenant")));
  });

  it("409 already-deleted → matching toast", async () => {
    apiGetMock.mockResolvedValue({ data: { items: [DUPLICATE] } });
    apiPostMock.mockRejectedValue({
      response: { status: 409,
                    data: { detail: "customer_already_deleted" } },
      message: "409",
    });
    render(
      <CustomerMergeWizard open={true} primary={PRIMARY}
                              onClose={vi.fn()} />,
    );
    fireEvent.change(screen.getByTestId("cmw-search-input"),
                        { target: { value: "ali" } });
    await waitFor(() => screen.getByTestId(
      `cmw-select-${DUPLICATE.id}`));
    fireEvent.click(screen.getByTestId(
      `cmw-select-${DUPLICATE.id}`));
    await waitFor(() => screen.getByTestId("cmw-resolver"));
    fireEvent.click(screen.getByTestId("cmw-next-btn"));
    await waitFor(() => screen.getByTestId("cmw-confirm"));
    fireEvent.change(screen.getByTestId("cmw-confirm-input"),
                        { target: { value: "MERGE" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("cmw-merge-btn"));
    });
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      expect.stringContaining("already deleted")));
  });

  // Phase M1.1 — warnings array is surfaced as info-level toasts.
  it("Warnings array in success response fires one info toast each",
    async () => {
      apiGetMock.mockResolvedValue({ data: { items: [DUPLICATE] } });
      apiPostMock.mockResolvedValue({
        data: {
          ok: true,
          primary_customer_id:   PRIMARY.id,
          duplicate_customer_id: DUPLICATE.id,
          reparent_counts:      { jobs: 1 },
          merged_at: "2026-02-20T10:00:00Z",
          warnings: [
            "Stripe customer records were not merged. …",
            "Both customers had portal logins — user records left "
            + "untouched. Manual review required in the admin users "
            + "panel.",
          ],
        },
      });
      const onMerged = vi.fn();
      render(
        <CustomerMergeWizard open={true} primary={PRIMARY}
                                onClose={vi.fn()} onMerged={onMerged} />,
      );
      fireEvent.change(screen.getByTestId("cmw-search-input"),
                          { target: { value: "ali" } });
      await waitFor(() => screen.getByTestId(
        `cmw-select-${DUPLICATE.id}`));
      fireEvent.click(screen.getByTestId(
        `cmw-select-${DUPLICATE.id}`));
      await waitFor(() => screen.getByTestId("cmw-resolver"));
      fireEvent.click(screen.getByTestId("cmw-next-btn"));
      await waitFor(() => screen.getByTestId("cmw-confirm"));
      fireEvent.change(screen.getByTestId("cmw-confirm-input"),
                          { target: { value: "MERGE" } });
      await act(async () => {
        fireEvent.click(screen.getByTestId("cmw-merge-btn"));
      });
      await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
      // Both warnings surfaced as info toasts.
      expect(toastInfo).toHaveBeenCalledTimes(2);
      expect(toastInfo).toHaveBeenNthCalledWith(1,
        expect.stringContaining("Stripe"),
        expect.objectContaining({ duration: expect.any(Number) }),
      );
      expect(toastInfo).toHaveBeenNthCalledWith(2,
        expect.stringContaining("portal logins"),
        expect.objectContaining({ duration: expect.any(Number) }),
      );
    });
});
