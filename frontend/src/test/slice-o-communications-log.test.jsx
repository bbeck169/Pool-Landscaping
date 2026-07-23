/**
 * Slice O · Feb-2026 — Communications Log page unit tests.
 *
 * Verifies:
 *   1. Empty state renders the "No communications match" copy.
 *   2. Rows render with correctly-toned status pills.
 *   3. Changing the channel filter causes a re-fetch (new URL params).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock("@/api", () => ({ api: { get: apiGetMock } }));

// Auth stub — admin sees the page.
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1", name: "Admin" } }),
}));

// Forbidden component is never reached in these tests, but the module
// imports it — keep the stub minimal to avoid pulling permission logic.
vi.mock("@/hooks/usePermissions", () => ({
  Forbidden: ({ reason }) => <div>{reason}</div>,
}));

import CommunicationsLogPage from
  "@/pages/marketing/CommunicationsLogPage";

function _summary(overrides = {}) {
  return {
    window_days: 30,
    total_sent: 0, email_sent: 0, sms_sent: 0,
    opened: 0, clicked: 0, bounced: 0, failed: 0,
    open_rate_pct: 0, click_rate_pct: 0, bounce_rate_pct: 0,
    ...overrides,
  };
}

function _mockCalls({ listItems = [], total = 0, summary = _summary() } = {}) {
  apiGetMock.mockImplementation((path) => {
    if (path.startsWith("/communications-log/summary")) {
      return Promise.resolve(summary);
    }
    if (path.startsWith("/communications-log")) {
      return Promise.resolve({ items: listItems, total, page: 1, page_size: 50 });
    }
    return Promise.resolve(null);
  });
}

beforeEach(() => { apiGetMock.mockReset(); });

describe("CommunicationsLogPage", () => {
  it("renders the empty state when zero rows come back", async () => {
    _mockCalls({ listItems: [], total: 0 });
    render(
      <MemoryRouter>
        <CommunicationsLogPage />
      </MemoryRouter>
    );
    const empty = await screen.findByTestId("comm-log-empty-state");
    expect(empty.textContent).toMatch(/No communications match/);
  });

  it("renders rows with a colored status pill matching status_derived", async () => {
    _mockCalls({
      listItems: [
        { id: "r1", channel: "email", customer_name: "Alice",
          recipient_email: "a@ex.com", subject: "Hi", body_preview: "",
          created_at: new Date().toISOString(),
          status_derived: "clicked", provider: "resend" },
      ],
      total: 1,
      summary: _summary({ total_sent: 1, email_sent: 1, clicked: 1,
                           click_rate_pct: 100 }),
    });
    render(
      <MemoryRouter>
        <CommunicationsLogPage />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("comm-log-row-r1")).toBeInTheDocument()
    );
    // Green "clicked" pill.
    expect(
      screen.getByTestId("comm-log-status-pill-clicked")
    ).toBeInTheDocument();
    // KPI card reflects the mocked summary.
    expect(screen.getByTestId("comm-log-kpi-total").textContent)
      .toMatch(/1/);
  });

  it("changing the channel filter re-fetches with channel=email", async () => {
    _mockCalls({ listItems: [], total: 0 });
    render(
      <MemoryRouter>
        <CommunicationsLogPage />
      </MemoryRouter>
    );
    // Wait for initial calls to settle.
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    apiGetMock.mockClear();
    _mockCalls({ listItems: [], total: 0 });

    fireEvent.click(screen.getByTestId("comm-log-filter-channel-email"));

    await waitFor(() => {
      const listCall = apiGetMock.mock.calls.find(
        ([p]) => p.startsWith("/communications-log?")
      );
      expect(listCall).toBeTruthy();
      expect(listCall[0]).toMatch(/channel=email/);
    });
  });
});
