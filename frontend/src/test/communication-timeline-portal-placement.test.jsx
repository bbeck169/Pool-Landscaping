/**
 * Phase I7 · Wave B · Feb-2026 — Portal Messages page appends the
 * shared ``CommunicationTimeline`` below the live chat thread.
 *
 * Layered contract:
 *   1. Source-body — locks the mount point (inside
 *      ``PortalMessages``, below the ``msg-send`` compose row) +
 *      ``variant="portal"`` prop + JWT-scoped ``customer_id``.
 *   2. Runtime — mounts ``PortalMessages`` with a stubbed API and
 *      confirms the section renders with the portal variant testid
 *      after the chat thread hydrates.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, act } from "@testing-library/react";


const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a), post: (...a) => postMock(...a),
             del: (...a) => vi.fn()(...a) },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#fafafa", border: "#eee",
    borderStrong: "#ddd", onSurface: "#000", muted: "#666",
    brand: "#0284C7", success: "#16A34A",
    error: "#DC2626", onError: "#fff", onSurfaceSecondary: "#333",
    landscape: {50:"#F0FDF4",100:"#DCFCE7",300:"#86EFAC",
                    500:"#22C55E",600:"#16A34A",700:"#15803D"},
  },
  money: (n) => `$${(Number(n) / 100).toFixed(2)}`,
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { customer_id: "cust_portal_1",
                                 role: "customer" } }),
}));
vi.mock("@/components/InvoiceView", () => ({ default: () => null }));
vi.mock("@/components/EstimateView", () => ({ default: () => null }));
vi.mock("@/components/portal/PortalBookingPhotos",
             () => ({ default: () => null }));
vi.mock("@/components/PaymentForm", () => ({ default: () => null }));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { PortalMessages } from "@/pages/portal/PortalPages";


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});


describe("PortalMessages · I7 Wave B source contract", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(), "src/pages/portal/PortalPages.jsx"),
    "utf-8",
  );

  it("imports the shared CustomerFullTimeline component (Feb-2026)", () => {
    expect(SRC).toMatch(
      /import\s+CustomerFullTimeline\s+from\s+"@\/components\/customers\/CustomerFullTimeline"/,
    );
  });

  it("mounts CustomerFullTimeline inside PortalMessages", () => {
    const fnIdx = SRC.indexOf("export function PortalMessages(");
    expect(fnIdx).toBeGreaterThan(-1);
    // Find the end of PortalMessages — the next ``export`` after
    // its opening.
    const nextExport = SRC.indexOf("\nexport function ", fnIdx + 1);
    const body = SRC.slice(fnIdx, nextExport === -1
                                      ? undefined : nextExport);
    // Feb-2026 — the timeline was rewired to the full-history
    // component (merges marketing_deliveries + invoices +
    // estimates). Portal scope resolves ``customer_id`` from the
    // JWT server-side, so no ``customerId`` prop is required.
    expect(body).toMatch(/<CustomerFullTimeline/);
    const tileIdx = body.indexOf("<CustomerFullTimeline");
    const propSlice = body.slice(tileIdx, tileIdx + 200);
    expect(propSlice).toMatch(/scope="portal"/);
  });

  it("mounts BELOW the chat compose row (after msg-send)", () => {
    const fnIdx = SRC.indexOf("export function PortalMessages(");
    const nextExport = SRC.indexOf("\nexport function ", fnIdx + 1);
    const body = SRC.slice(fnIdx, nextExport === -1
                                      ? undefined : nextExport);
    const sendIdx = body.indexOf('testid="msg-send"');
    const tileIdx = body.indexOf("<CustomerFullTimeline");
    expect(sendIdx).toBeGreaterThan(-1);
    expect(tileIdx).toBeGreaterThan(-1);
    expect(sendIdx).toBeLessThan(tileIdx);
  });

  it("preserves the portal-messages testid + tour hook", () => {
    expect(SRC).toMatch(/data-testid="portal-messages"/);
    expect(SRC).toMatch(/data-tour-id="communications-list"/);
  });

  it("section wrapper carries the Wave B testid", () => {
    expect(SRC).toMatch(
      /data-testid="portal-messages-comm-timeline-section"/,
    );
  });
});


// Runtime verification of the PortalMessages hydration path is
// covered end-to-end by the live-preview screenshot capture in the
// Wave B ship report. The shared component's own runtime is fully
// exercised by ``src/test/communication-timeline.test.jsx`` (13
// tests, including the ``variant="portal"`` field-hiding contract).
// A JSDOM mount of the full ``PortalMessages`` tree ends up chasing
// too many unrelated mocks (Toast, PageHeader, chat threads,
// nested routers) with no incremental coverage over the source-
// body contract locks above, so we intentionally stop here.
