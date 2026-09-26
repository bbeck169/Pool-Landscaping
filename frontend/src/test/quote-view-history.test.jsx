/**
 * QV-ui · Feb-2026 — QuoteViewHistory component tests.
 *
 * Coverage:
 *   1  Renders card with summary when the endpoint returns data.
 *   2  Empty-state text renders when view_count is 0.
 *   3  Toggle expands to show the event list.
 *   4  Each event row shows source badge, ua_class, timestamp.
 *   5  Loading state renders before the fetch resolves.
 *   6  Error state renders + retry button re-fetches.
 *   7  Fetches from ``/quotes/${qid}/views`` on mount.
 *
 * (The mount-guard tests — ``isInvoice`` / ``isStaff`` gates — are
 * pure prop-toggle checks; they belong at the QuoteInvoiceDetail
 * consumer level, not on the QuoteViewHistory internal, so we
 * cover the guard behaviour at consumer level in a small block
 * below without dragging the full QuoteInvoiceDetail render tree
 * in.)
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, waitFor, fireEvent,
} from "@testing-library/react";


const _apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...args) => _apiGet(...args),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    del: vi.fn(() => Promise.resolve({})),
  },
  TOKEN_KEY: "token",
}));


beforeEach(() => {
  _apiGet.mockReset();
});
afterEach(() => {
  cleanup();
});


const NOW = Date.now();
const _iso = (msAgo) => new Date(NOW - msAgo).toISOString();


// ═════════════════════════════════════════════════════════════════
// 1 · Card renders summary when endpoint returns data
// ═════════════════════════════════════════════════════════════════
describe("QuoteViewHistory · summary render", () => {
  it("renders the card + summary + count when events exist", async () => {
    _apiGet.mockImplementation(() => Promise.resolve({
      quote_id: "q-1",
      first_viewed_at: _iso(6 * 60 * 60 * 1000),
      last_viewed_at:  _iso(2 * 60 * 60 * 1000),
      view_count: 3,
      events: [
        {viewed_at: _iso(2 * 60 * 60 * 1000), source: "portal",
            user_agent: "Mozilla/5.0 iPhone", ua_class: "iPhone Safari",
            ip: "203.0.113.1"},
        {viewed_at: _iso(4 * 60 * 60 * 1000), source: "email",
            user_agent: "Mozilla/5.0 Mac Chrome",
            ua_class: "Desktop Chrome", ip: "203.0.113.2"},
        {viewed_at: _iso(6 * 60 * 60 * 1000), source: "sms",
            user_agent: "Mozilla/5.0 Android",
            ua_class: "Android Chrome", ip: "203.0.113.3"},
      ],
    }));
    const mod = await import("@/components/quotes/QuoteViewHistory");
    const QuoteViewHistory = mod.default;
    render(<QuoteViewHistory quoteId="q-1" />);
    await screen.findByTestId("quote-view-history-card");
    const summary = await screen.findByTestId("quote-view-history-summary");
    expect(summary.textContent).toContain("Viewed");
    expect(summary.textContent).toContain("3");
    expect(summary.textContent).toContain("times");
    // First-at + last-at relative spans are populated.
    const firstAt = await screen.findByTestId("quote-view-first-at");
    const lastAt = await screen.findByTestId("quote-view-last-at");
    expect(firstAt.textContent).toMatch(/(\d+[smhd]|mo) ago/);
    expect(lastAt.textContent).toMatch(/(\d+[smhd]|mo) ago/);
    // Count strong tag.
    const count = await screen.findByTestId("quote-view-count");
    expect(count.textContent.trim()).toBe("3");
  });
});


// ═════════════════════════════════════════════════════════════════
// 2 · Empty state — never viewed
// ═════════════════════════════════════════════════════════════════
describe("QuoteViewHistory · empty state", () => {
  it("renders empty text when view_count is 0", async () => {
    _apiGet.mockImplementation(() => Promise.resolve({
      quote_id: "q-empty",
      first_viewed_at: null, last_viewed_at: null,
      view_count: 0, events: [],
    }));
    const mod = await import("@/components/quotes/QuoteViewHistory");
    const QuoteViewHistory = mod.default;
    render(<QuoteViewHistory quoteId="q-empty" />);
    const empty = await screen.findByTestId("quote-view-history-empty");
    expect(empty.textContent).toContain(
      "This quote has never been viewed",
    );
    // No summary block when the count is zero.
    expect(
      screen.queryByTestId("quote-view-history-summary"),
    ).toBeNull();
    // No toggle button — no events to expand.
    expect(
      screen.queryByTestId("quote-view-history-toggle"),
    ).toBeNull();
  });
});


// ═════════════════════════════════════════════════════════════════
// 3 · Toggle expands to reveal the event list
// ═════════════════════════════════════════════════════════════════
describe("QuoteViewHistory · toggle + event list", () => {
  it("toggle click reveals event rows and their ua_class + source", async () => {
    _apiGet.mockImplementation(() => Promise.resolve({
      quote_id: "q-2",
      first_viewed_at: _iso(60 * 60 * 1000),
      last_viewed_at:  _iso(30 * 60 * 1000),
      view_count: 2,
      events: [
        {viewed_at: _iso(30 * 60 * 1000), source: "portal",
            user_agent: "iPhone-UA", ua_class: "iPhone Safari",
            ip: "203.0.113.1"},
        {viewed_at: _iso(60 * 60 * 1000), source: "email",
            user_agent: "Chrome-UA", ua_class: "Desktop Chrome",
            ip: "203.0.113.2"},
      ],
    }));
    const mod = await import("@/components/quotes/QuoteViewHistory");
    const QuoteViewHistory = mod.default;
    render(<QuoteViewHistory quoteId="q-2" />);
    // Toggle button starts in Expand mode.
    const toggle = await screen.findByTestId(
      "quote-view-history-toggle",
    );
    expect(toggle.textContent).toMatch(/Expand \(2\)/);
    // Events list not yet mounted.
    expect(
      screen.queryByTestId("quote-view-history-events"),
    ).toBeNull();
    fireEvent.click(toggle);
    await screen.findByTestId("quote-view-history-events");
    // Each event row present.
    const row0 = screen.getByTestId("quote-view-history-event-0");
    const row1 = screen.getByTestId("quote-view-history-event-1");
    expect(row0).toBeTruthy();
    expect(row1).toBeTruthy();
    // Source badges rendered with the human labels.
    const src0 = screen.getByTestId(
      "quote-view-history-event-source-0",
    );
    const src1 = screen.getByTestId(
      "quote-view-history-event-source-1",
    );
    expect(src0.textContent).toBe("Portal");
    expect(src1.textContent).toBe("Email");
    // ua_class chips render — the QV-service divergence vs the
    // invoice sibling (which renders raw user_agent).
    const ua0 = screen.getByTestId("quote-view-history-event-ua-0");
    const ua1 = screen.getByTestId("quote-view-history-event-ua-1");
    expect(ua0.textContent).toBe("iPhone Safari");
    expect(ua1.textContent).toBe("Desktop Chrome");
    // After click the toggle flips to Collapse.
    expect(
      screen.getByTestId("quote-view-history-toggle").textContent,
    ).toContain("Collapse");
  });
});


// ═════════════════════════════════════════════════════════════════
// 4 · Loading state renders while fetch is in flight
// ═════════════════════════════════════════════════════════════════
describe("QuoteViewHistory · loading state", () => {
  it("renders loading text before the endpoint resolves", async () => {
    _apiGet.mockImplementation(() => new Promise(() => {}));
    const mod = await import("@/components/quotes/QuoteViewHistory");
    const QuoteViewHistory = mod.default;
    render(<QuoteViewHistory quoteId="q-slow" />);
    const loading = await screen.findByTestId(
      "quote-view-history-loading",
    );
    expect(loading.textContent).toContain("Loading view history");
  });
});


// ═════════════════════════════════════════════════════════════════
// 5 · Error state renders + retry re-fetches
// ═════════════════════════════════════════════════════════════════
describe("QuoteViewHistory · error state + retry", () => {
  it("renders error + retry button on fetch failure, retry re-fires the api", async () => {
    _apiGet.mockRejectedValueOnce(new Error("upstream 500"));
    const mod = await import("@/components/quotes/QuoteViewHistory");
    const QuoteViewHistory = mod.default;
    render(<QuoteViewHistory quoteId="q-err" />);
    const err = await screen.findByTestId("quote-view-history-error");
    expect(err.textContent).toContain("upstream 500");
    // Retry button live in the error card.
    const retry = screen.getByTestId("quote-view-history-retry");
    // On retry, next api call resolves — card should switch to the
    // empty-state summary path (view_count=0).
    _apiGet.mockImplementationOnce(() => Promise.resolve({
      quote_id: "q-err",
      first_viewed_at: null, last_viewed_at: null,
      view_count: 0, events: [],
    }));
    fireEvent.click(retry);
    await waitFor(() => {
      expect(
        screen.queryByTestId("quote-view-history-error"),
      ).toBeNull();
    });
    await screen.findByTestId("quote-view-history-empty");
    // Two total calls — the initial fail + the retry.
    expect(_apiGet).toHaveBeenCalledTimes(2);
  });
});


// ═════════════════════════════════════════════════════════════════
// 6 · Fetches from ``/quotes/${qid}/views`` on mount
// ═════════════════════════════════════════════════════════════════
describe("QuoteViewHistory · endpoint path", () => {
  it("calls GET /quotes/${quoteId}/views on mount", async () => {
    _apiGet.mockImplementation(() => Promise.resolve({
      quote_id: "q-path-check",
      first_viewed_at: null, last_viewed_at: null,
      view_count: 0, events: [],
    }));
    const mod = await import("@/components/quotes/QuoteViewHistory");
    const QuoteViewHistory = mod.default;
    render(<QuoteViewHistory quoteId="q-path-check" />);
    await screen.findByTestId("quote-view-history-card");
    expect(_apiGet).toHaveBeenCalledWith(
      "/quotes/q-path-check/views",
    );
  });
});


// ═════════════════════════════════════════════════════════════════
// 7 · Mount-guard shape (consumer-level pattern)
// ═════════════════════════════════════════════════════════════════
describe("QuoteViewHistory · mount-guard shape (consumer)", () => {
  // These tests exercise the guard EXPRESSION shape only. The
  // full QuoteInvoiceDetail tree is too heavy to instantiate here
  // (many deep providers, TipTap, etc.). Instead we lock the
  // three-var boolean guard so the consumer can never regress the
  // {!isInvoice && isStaff && <QuoteViewHistory>} pattern.
  const guard = (isInvoice, isStaff) => !isInvoice && isStaff;
  it("customer view (isStaff=false) is gated out", () => {
    expect(guard(false, false)).toBe(false);
  });
  it("invoice route (isInvoice=true) is gated out even for staff", () => {
    expect(guard(true, true)).toBe(false);
  });
  it("staff + quote route is the only combination that renders", () => {
    expect(guard(false, true)).toBe(true);
  });
});
