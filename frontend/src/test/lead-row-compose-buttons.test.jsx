/**
 * Phase L3 · Feb-2026 · Leads list — row-level compose buttons.
 *
 * Coverage:
 *  1. Row-level SMS + Email icon buttons are visible for admin users.
 *  2. Buttons are DISABLED when the identity (phone/email) is missing
 *     — with an aria-label + tooltip title explaining why.
 *  3. Non-privileged roles (e.g. technician / customer) never see the
 *     compose buttons at all.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), post: (...a) => apiPost(...a), del: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(() => Promise.resolve(true)),
}));

const authState = { user: { role: "admin", email: "a@t" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));

async function tick() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  authState.user = { role: "admin", email: "a@t" };
});

const ROWS = [
  { id: "L1", name: "Alice", email: "alice@example.com",
    phone: "+15555550100", source: "website_form", status: "new",
    created_at: "2026-02-01" },
  { id: "L2", name: "Bob", email: null, phone: null,
    source: "website_form", status: "new",
    created_at: "2026-02-01" },
];


describe("Leads list · row-level compose buttons", () => {
  it("renders enabled SMS + email icons on a row with phone + email", async () => {
    apiGet.mockResolvedValueOnce({ rows: ROWS, total: 2 });
    const { default: LeadsDashboardPage } =
      await import("@/pages/leads/LeadsDashboardPage");
    render(<MemoryRouter><LeadsDashboardPage /></MemoryRouter>);
    await tick();

    const smsBtn = screen.getByTestId("lead-row-sms-L1");
    const emailBtn = screen.getByTestId("lead-row-email-L1");
    expect(smsBtn).toBeInTheDocument();
    expect(emailBtn).toBeInTheDocument();
    expect(smsBtn).not.toBeDisabled();
    expect(emailBtn).not.toBeDisabled();
    // Aria labels present for icon-only buttons.
    expect(smsBtn.getAttribute("aria-label")).toMatch(/SMS/i);
    expect(emailBtn.getAttribute("aria-label")).toMatch(/email/i);
  });

  it("disables buttons + shows tooltip when phone/email is missing", async () => {
    apiGet.mockResolvedValueOnce({ rows: ROWS, total: 2 });
    const { default: LeadsDashboardPage } =
      await import("@/pages/leads/LeadsDashboardPage");
    render(<MemoryRouter><LeadsDashboardPage /></MemoryRouter>);
    await tick();

    const smsBtn = screen.getByTestId("lead-row-sms-L2");
    const emailBtn = screen.getByTestId("lead-row-email-L2");
    expect(smsBtn).toBeDisabled();
    expect(emailBtn).toBeDisabled();
    expect(smsBtn.getAttribute("title")).toMatch(/no phone/i);
    expect(emailBtn.getAttribute("title")).toMatch(/no email/i);
  });

  it("hides the buttons entirely for non-privileged roles", async () => {
    authState.user = { role: "technician", email: "t@t" };
    apiGet.mockResolvedValueOnce({ rows: ROWS, total: 2 });
    const { default: LeadsDashboardPage } =
      await import("@/pages/leads/LeadsDashboardPage");
    render(<MemoryRouter><LeadsDashboardPage /></MemoryRouter>);
    await tick();

    expect(screen.queryByTestId("lead-row-sms-L1")).toBeNull();
    expect(screen.queryByTestId("lead-row-email-L1")).toBeNull();
  });
});
