/**
 * Phase L3 · Feb-2026 · Lead detail — Communication Timeline.
 *
 * Coverage:
 *  1. Renders SMS + email items in DESC order (newest first), each
 *     with its channel-labeled badge.
 *  2. When ``has_more=true``, a "Load more" button appears and drives
 *     a second fetch with the returned cursor.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    patch: (...a) => apiPatch(...a),
    del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const authState = { user: { role: "admin", email: "a@t" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));

// The click-to-call telephony subtree drags dial-plan providers +
// tenant lookups — mock it out so we can mount the page in isolation.
vi.mock("@/components/telephony/ClickToCallButton", () => ({
  default: () => null,
}));

async function tick() {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPatch.mockReset();
});

const LEAD = {
  id: "lead-1", name: "Alice", email: "alice@example.com",
  phone: "+15555550100", status: "new",
  source: "website_form", created_at: "2026-02-01T10:00:00Z",
  timeline: [],
};


describe("LeadDetail · Communication Timeline", () => {
  it("renders SMS + email items in DESC order with channel badges", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/leads/lead-1") return Promise.resolve(LEAD);
      if (path.startsWith("/leads/lead-1/communications")) {
        return Promise.resolve({
          items: [
            // Newest first (DESC).
            { id: "c2", type: "email", direction: "outbound",
              subject: "Following up", body: "Hi Alice,",
              status: "sent", created_at: "2026-02-01T14:00:00Z" },
            { id: "c1", type: "sms", direction: "outbound",
              body: "Hi following up on your quote",
              status: "sent", created_at: "2026-02-01T13:00:00Z" },
          ],
          next_cursor: null, has_more: false,
        });
      }
      return Promise.resolve({});
    });

    const { default: LeadDetail } =
      await import("@/pages/leads/LeadDetail");

    render(
      <MemoryRouter initialEntries={["/leads/lead-1"]}>
        <Routes>
          <Route path="/leads/:id" element={<LeadDetail />} />
        </Routes>
      </MemoryRouter>,
    );
    await tick();

    await waitFor(() => {
      expect(screen.getByTestId("lead-communication-timeline"))
        .toBeInTheDocument();
    });
    const timeline = screen.getByTestId("lead-communication-timeline");
    const emailBadges = timeline.querySelectorAll(
      "[data-testid='lead-comm-item-email']",
    );
    const smsBadges = timeline.querySelectorAll(
      "[data-testid='lead-comm-item-sms']",
    );
    expect(emailBadges.length).toBe(1);
    expect(smsBadges.length).toBe(1);
    // DOM order matches DESC order — email (newest) BEFORE sms.
    const items = timeline.querySelectorAll(
      "[data-testid^='lead-comm-item-']",
    );
    expect(items[0].getAttribute("data-testid")).toBe("lead-comm-item-email");
    expect(items[1].getAttribute("data-testid")).toBe("lead-comm-item-sms");
  });

  it("shows Load more when has_more=true and fetches with the cursor", async () => {
    let call = 0;
    apiGet.mockImplementation((path) => {
      if (path === "/leads/lead-1") return Promise.resolve(LEAD);
      if (path.startsWith("/leads/lead-1/communications")) {
        call += 1;
        if (call === 1) {
          return Promise.resolve({
            items: [
              { id: "c1", type: "sms", direction: "outbound",
                body: "one", status: "sent",
                created_at: "2026-02-01T14:00:00Z" },
            ],
            next_cursor: "2026-02-01T14:00:00Z|c1",
            has_more: true,
          });
        }
        // second call must carry the cursor
        expect(path).toContain("cursor=2026-02-01T14%3A00%3A00Z%7Cc1");
        return Promise.resolve({
          items: [
            { id: "c0", type: "sms", direction: "outbound",
              body: "zero", status: "sent",
              created_at: "2026-02-01T13:00:00Z" },
          ],
          next_cursor: null, has_more: false,
        });
      }
      return Promise.resolve({});
    });

    const { default: LeadDetail } =
      await import("@/pages/leads/LeadDetail");

    render(
      <MemoryRouter initialEntries={["/leads/lead-1"]}>
        <Routes>
          <Route path="/leads/:id" element={<LeadDetail />} />
        </Routes>
      </MemoryRouter>,
    );
    await tick();

    const loadMore = await screen.findByTestId(
      "lead-communication-timeline-load-more",
    );
    fireEvent.click(loadMore);
    await tick();

    // After the second fetch, there should be 2 SMS items on the DOM.
    await waitFor(() => {
      const timeline = screen.getByTestId("lead-communication-timeline");
      const smsItems = timeline.querySelectorAll(
        "[data-testid='lead-comm-item-sms']",
      );
      expect(smsItems.length).toBe(2);
    });
  });
});
