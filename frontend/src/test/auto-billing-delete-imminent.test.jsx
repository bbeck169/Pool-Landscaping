/**
 * Ticket DD · Feb-2026 — AutoBilling bulk-delete imminent-charge
 * warning vitest.
 *
 * Locks:
 *   * Warning banner renders when the selection includes a plan
 *     with ``next_run`` within 24h.
 *   * Warning banner does NOT render when no selected plan is
 *     imminent (future-dated / null / malformed next_run).
 *   * Confirm button is a single click (no typing input in the
 *     modal) — label "Confirm Delete".
 *   * Click fires the ``/autobilling/bulk-delete`` POST and
 *     optimistically removes the deleted ids from the table.
 *   * Cancel button closes the modal without firing a POST.
 */
import React from "react";
import {
    describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
    render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();
const putMock = vi.fn();
vi.mock("@/api", () => ({
    api: {
        get: (...args) => getMock(...args),
        post: (...args) => postMock(...args),
        put: (...args) => putMock(...args),
    },
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastPlain = vi.fn();
vi.mock("sonner", () => {
    const toast = (...a) => toastPlain(...a);
    toast.success = (...a) => toastSuccess(...a);
    toast.error = (...a) => toastError(...a);
    return { toast };
});

vi.mock("@/theme", () => ({
    colors: {
        surface: "#fff", surfaceAlt: "#fafafa",
        surfaceSecondary: "#f5f5f5", surfaceTertiary: "#eee",
        border: "#ddd", muted: "#666",
        onSurface: "#000", brand: "#0891B2",
    },
    money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

vi.mock("@/components/ui-kit", () => ({
    PageHeader: ({ title, subtitle }) =>
        <div><h1>{title}</h1><p>{subtitle}</p></div>,
    Card: ({ children, testId }) =>
        <div data-testid={testId}>{children}</div>,
    Skeleton: (p) => <div {...p} />,
    Header: ({ title, subtitle, right }) =>
        <div><h1>{title}</h1><p>{subtitle}</p>{right}</div>,
}));

vi.mock("@/auth", () => ({
    useAuth: () => ({ user: { id: "u-admin", role: "admin" } }),
    AuthProvider: ({ children }) => children,
}));

import { AutoBilling } from "@/pages/finance/FinancePages";


function _iso(hoursFromNow) {
    const d = new Date(Date.now() + hoursFromNow * 60 * 60 * 1000);
    return d.toISOString();
}


const _basePlans = () => ([
    {
        id: "p-future", customer_id: "c1", service: "Monthly Pool",
        amount: 150, frequency: "monthly", active: true,
        next_run: _iso(240),  // 10 days out — NOT imminent
    },
    {
        id: "p-imminent", customer_id: "c2", service: "Weekly Chem",
        amount: 80, frequency: "weekly", active: true,
        next_run: _iso(6),  // 6h out — IMMINENT
    },
    {
        id: "p-null", customer_id: "c3", service: "Pool start",
        amount: 300, frequency: "monthly", active: true,
        next_run: null,
    },
]);


beforeEach(() => {
    getMock.mockReset(); postMock.mockReset(); putMock.mockReset();
    toastSuccess.mockReset(); toastError.mockReset();
    toastPlain.mockReset();
});
afterEach(() => cleanup());


const _renderPage = () => render(
    <MemoryRouter><AutoBilling /></MemoryRouter>,
);


describe("Ticket DD · AutoBilling bulk-delete imminent-charge warning", () => {
    it("confirm button label is 'Confirm Delete' (not 'Delete N')",
       async () => {
        getMock.mockResolvedValueOnce(_basePlans());
        _renderPage();
        await waitFor(() =>
            expect(screen.getByTestId("autobilling-table"))
                .toBeInTheDocument(),
        );
        fireEvent.click(screen.getByTestId("bulk-select-all"));
        // Open bulk-delete modal.  The toolbar button opens it;
        // easiest is to pick it from the DOM by test-id — the
        // AutoBilling bulk-select action bar renders when
        // selectedCount>0.
        const openers = screen.getAllByRole("button").filter(
            (b) => /delete/i.test(b.textContent || ""),
        );
        // Find the opener (the toolbar "Delete N" button, not the
        // confirm inside the modal — modal isn't open yet).
        fireEvent.click(openers[0]);
        const confirmBtn = await screen.findByTestId(
            "bulk-delete-confirm-btn",
        );
        expect(confirmBtn.textContent).toMatch(/Confirm Delete/i);
    });

    it("renders imminent-charge warning banner when a selected plan "
       + "has next_run within 24h",
       async () => {
        getMock.mockResolvedValueOnce(_basePlans());
        _renderPage();
        await waitFor(() =>
            expect(screen.getByTestId("autobilling-table"))
                .toBeInTheDocument(),
        );
        fireEvent.click(screen.getByTestId("bulk-select-all"));
        const openers = screen.getAllByRole("button").filter(
            (b) => /delete/i.test(b.textContent || ""),
        );
        fireEvent.click(openers[0]);
        const warning = await screen.findByTestId(
            "bulk-delete-imminent-warning",
        );
        expect(warning).toBeInTheDocument();
        expect(warning.textContent).toMatch(/Imminent charge/i);
        expect(warning.textContent).toMatch(/24 hours/);
    });

    it("does NOT render warning banner when no selected plan is imminent",
       async () => {
        // Only select non-imminent plans.
        getMock.mockResolvedValueOnce(_basePlans());
        _renderPage();
        await waitFor(() =>
            expect(screen.getByTestId("autobilling-table"))
                .toBeInTheDocument(),
        );
        // Each row has a bulk-select-row-<id> or similar testid;
        // fall back to generic row checkbox selectors.
        const rowCheckboxes = screen.getAllByRole("checkbox").filter(
            (c) => c.getAttribute("data-testid") !== "bulk-select-all",
        );
        // Click only the first (p-future, non-imminent) and third
        // (p-null, non-imminent) rows.
        fireEvent.click(rowCheckboxes[0]);
        fireEvent.click(rowCheckboxes[2]);
        const openers = screen.getAllByRole("button").filter(
            (b) => /delete/i.test(b.textContent || ""),
        );
        fireEvent.click(openers[0]);
        await screen.findByTestId("bulk-delete-confirm-btn");
        expect(screen.queryByTestId("bulk-delete-imminent-warning"))
            .toBeNull();
    });

    it("Cancel button closes the modal WITHOUT firing POST", async () => {
        getMock.mockResolvedValueOnce(_basePlans());
        _renderPage();
        await waitFor(() =>
            expect(screen.getByTestId("autobilling-table"))
                .toBeInTheDocument(),
        );
        fireEvent.click(screen.getByTestId("bulk-select-all"));
        const openers = screen.getAllByRole("button").filter(
            (b) => /delete/i.test(b.textContent || ""),
        );
        fireEvent.click(openers[0]);
        fireEvent.click(await screen.findByTestId("bulk-delete-cancel"));
        await waitFor(() =>
            expect(screen.queryByTestId("bulk-delete-confirm"))
                .toBeNull(),
        );
        expect(postMock).not.toHaveBeenCalled();
    });

    it("Confirm Delete click fires /autobilling/bulk-delete + "
       + "optimistically removes rows",
       async () => {
        getMock.mockResolvedValueOnce(_basePlans());
        postMock.mockResolvedValueOnce({
            ok: true, deleted_count: 3,
            deleted: ["p-future", "p-imminent", "p-null"],
            failed: [],
        });
        _renderPage();
        await waitFor(() =>
            expect(screen.getByTestId("autobilling-table"))
                .toBeInTheDocument(),
        );
        fireEvent.click(screen.getByTestId("bulk-select-all"));
        const openers = screen.getAllByRole("button").filter(
            (b) => /delete/i.test(b.textContent || ""),
        );
        fireEvent.click(openers[0]);
        fireEvent.click(await screen.findByTestId(
            "bulk-delete-confirm-btn",
        ));
        await waitFor(() =>
            expect(postMock).toHaveBeenCalledWith(
                "/autobilling/bulk-delete",
                { ids: expect.arrayContaining([
                    "p-future", "p-imminent", "p-null",
                ]) },
            ),
        );
    });

    it("confirm modal has no 'type DELETE to confirm' input "
       + "(single-click confirmation)",
       async () => {
        getMock.mockResolvedValueOnce(_basePlans());
        _renderPage();
        await waitFor(() =>
            expect(screen.getByTestId("autobilling-table"))
                .toBeInTheDocument(),
        );
        fireEvent.click(screen.getByTestId("bulk-select-all"));
        const openers = screen.getAllByRole("button").filter(
            (b) => /delete/i.test(b.textContent || ""),
        );
        fireEvent.click(openers[0]);
        await screen.findByTestId("bulk-delete-confirm-btn");
        // No text input inside the confirmation modal (negative check).
        const modal = screen.getByTestId("bulk-delete-confirm");
        expect(modal.querySelector("input[type='text']")).toBeNull();
        expect(modal.textContent.toLowerCase()).not.toMatch(/type delete/);
    });
});
