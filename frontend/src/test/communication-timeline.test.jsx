/**
 * Phase I7 · Wave A · Feb-2026 — CommunicationTimeline component +
 * admin CustomerDetail placement.
 *
 * Layered coverage:
 *   1. Runtime — mocked ``@/api`` drives the component through its
 *      loading → populated → load-more paths.  Timeline pills, actor
 *      formatting, admin-only status pill + error line, and portal
 *      variant field-hiding are all locked here.
 *   2. Source-body — admin CustomerDetail must import + render the
 *      component inside the ``timeline`` tab branch, with the tab
 *      entry positioned between ``notes`` and ``credits`` in the tab
 *      list (matches the human's mockup).
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a) },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#fafafa",
    border: "#eee", borderStrong: "#ddd",
    onSurface: "#000", muted: "#666",
    brand: "#0284C7",
  },
}));

import CommunicationTimeline
  from "@/components/customers/CommunicationTimeline";


const SMS_ROW = {
  id: "row_sms_1", type: "sms",
  occurred_at: "2026-02-14T09:00:00Z",
  actor_label: "admin@aquaterra.com", actor_kind: "user",
  actor_user_id: "u_admin",
  direction: "outbound", channel_id: "ndl_1",
  subject: null, body_preview: "Hey — heads up we're rolling by tomorrow at 9am.",
  recipient: "+15555550100",
  delivery_status: "delivered",
  delivery_error: null,
};
const EMAIL_ROW = {
  id: "row_email_1", type: "email",
  occurred_at: "2026-02-13T09:00:00Z",
  actor_label: "System / Automation", actor_kind: "system",
  actor_user_id: null,
  direction: "outbound", channel_id: "ndl_2",
  subject: "Invoice #INV-42 is ready",
  body_preview: "Your invoice for last week's service is attached.",
  recipient: "customer@example.com",
  delivery_status: "failed",
  delivery_error: "bounce: mailbox_full",
};


beforeEach(() => { getMock.mockReset(); });


describe("CommunicationTimeline · I7 Wave A runtime", () => {
  it("shows loading skeleton until data resolves", async () => {
    let resolve;
    getMock.mockReturnValue(new Promise((r) => { resolve = r; }));
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1" />);
    });
    expect(screen.getByTestId(
      "communication-timeline-loading")).toBeInTheDocument();
    await act(async () => {
      resolve({items: [], has_more: false, next_before: null});
    });
    await waitFor(() => expect(screen.queryByTestId(
      "communication-timeline-loading")).not.toBeInTheDocument());
  });

  it("renders empty state when no comms exist", async () => {
    getMock.mockResolvedValue({items: [], has_more: false});
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1" />);
    });
    expect(await screen.findByTestId(
      "communication-timeline-empty")).toHaveTextContent(
        /No email or SMS communications yet/);
  });

  it("renders red SMS pill + green Email pill with correct copy", async () => {
    getMock.mockResolvedValue({items: [SMS_ROW, EMAIL_ROW],
                                     has_more: false});
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1" />);
    });
    await screen.findByTestId(`timeline-row-${SMS_ROW.id}`);
    const smsPills = screen.getAllByTestId("timeline-pill-sms");
    expect(smsPills[0]).toHaveTextContent(/Message/);
    const emailPills = screen.getAllByTestId("timeline-pill-email");
    expect(emailPills[0]).toHaveTextContent(/Email/);
    // Email row shows bold "Subject:" line.
    expect(screen.getByTestId(`timeline-subject-${EMAIL_ROW.id}`)
    ).toHaveTextContent(/Subject: Invoice #INV-42 is ready/);
  });

  it("actor label renders bolded next to 'by'", async () => {
    getMock.mockResolvedValue({items: [SMS_ROW], has_more: false});
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1" />);
    });
    const actor = await screen.findByTestId(
      `timeline-actor-${SMS_ROW.id}`);
    expect(actor).toHaveTextContent("admin@aquaterra.com");
    expect(actor.className).toMatch(/font-bold/);
  });

  it("admin variant surfaces delivery-status pill + error line", async () => {
    getMock.mockResolvedValue({items: [EMAIL_ROW], has_more: false});
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1"
                                                variant="admin" />);
    });
    expect(await screen.findByTestId(
      `timeline-status-${EMAIL_ROW.id}`)).toHaveTextContent(/failed/i);
    expect(screen.getByTestId(`timeline-error-${EMAIL_ROW.id}`)
    ).toHaveTextContent(/bounce: mailbox_full/);
  });

  it("portal variant hides delivery-status pill + error line", async () => {
    // Simulate the server having stripped admin-only fields.
    const stripped = { ...EMAIL_ROW };
    delete stripped.delivery_error;
    delete stripped.actor_user_id;
    getMock.mockResolvedValue({items: [stripped], has_more: false});
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1"
                                                variant="portal" />);
    });
    await screen.findByTestId(`timeline-row-${stripped.id}`);
    expect(screen.queryByTestId(`timeline-status-${stripped.id}`)
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId(`timeline-error-${stripped.id}`)
    ).not.toBeInTheDocument();
    // Wrapper testid switches to the portal variant.
    expect(screen.getByTestId("communication-timeline-portal")
    ).toBeInTheDocument();
  });

  it("load-more fires with the next_before cursor and appends items",
     async () => {
    getMock.mockResolvedValueOnce({
      items: [SMS_ROW],
      has_more: true,
      next_before: SMS_ROW.occurred_at,
    });
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1" limit={1} />);
    });
    await screen.findByTestId(`timeline-row-${SMS_ROW.id}`);
    // Load-more button appears.
    const btn = screen.getByTestId("communication-timeline-load-more");
    getMock.mockResolvedValueOnce({
      items: [EMAIL_ROW], has_more: false, next_before: null,
    });
    await act(async () => { fireEvent.click(btn); });
    // Second fetch carried the ``before`` cursor.
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    const secondUrl = getMock.mock.calls[1][0];
    expect(secondUrl).toMatch(
      /\/customers\/cust_1\/communication-timeline\?/);
    expect(secondUrl).toMatch(
      new RegExp(`before=${encodeURIComponent(SMS_ROW.occurred_at)}`),
    );
    // Both rows now visible.
    expect(screen.getByTestId(`timeline-row-${SMS_ROW.id}`)
    ).toBeInTheDocument();
    expect(await screen.findByTestId(
      `timeline-row-${EMAIL_ROW.id}`)).toBeInTheDocument();
  });

  it("skips fetch when customerId prop is missing", async () => {
    await act(async () => {
      render(<CommunicationTimeline customerId={null} />);
    });
    expect(getMock).not.toHaveBeenCalled();
  });

  it("error state surfaces via the error banner", async () => {
    getMock.mockRejectedValue(new Error("boom"));
    await act(async () => {
      render(<CommunicationTimeline customerId="cust_1" />);
    });
    expect(await screen.findByTestId(
      "communication-timeline-error")).toHaveTextContent("boom");
  });
});


// ═══════════════════════════════════════════════════════════════════
// Admin placement — locks the Timeline tab position + tab render.
// ═══════════════════════════════════════════════════════════════════
describe("CommunicationTimeline · admin placement in CustomerDetail",
             () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/pages/customers/CustomerDetail.jsx"),
    "utf-8",
  );

  it("imports the shared component", () => {
    expect(SRC).toMatch(
      /import\s+CommunicationTimeline\s+from\s+"@\/components\/customers\/CommunicationTimeline"/,
    );
  });

  it("does NOT add a Timeline tab to the tab list (revised placement)", () => {
    // Wave A revision — the previous ``{k: "timeline"…}`` tab
    // entry was removed in favor of a bottom-of-page section.
    expect(SRC).not.toMatch(/\{\s*k:\s*"timeline",\s*label:\s*"Timeline"/);
  });

  it("mounts CommunicationTimeline OUTSIDE the tab-panel switch (always visible)", () => {
    // The mount must NOT be gated by a ``tab === "..."`` ternary.
    // Contract: the ``<CommunicationTimeline`` occurrence in the
    // file must be preceded by the timeline SECTION wrapper testid
    // (``customer-detail-comm-timeline-section``), not by a tab
    // conditional.
    const idx = SRC.indexOf("<CommunicationTimeline");
    expect(idx).toBeGreaterThan(-1);
    const preamble = SRC.slice(Math.max(0, idx - 600), idx);
    expect(preamble).toMatch(
      /data-testid="customer-detail-comm-timeline-section"/,
    );
    // Guard against a future regression that re-adds a tab gate.
    const scan = SRC.slice(Math.max(0, idx - 200), idx);
    expect(scan).not.toMatch(/tab\s*===\s*"timeline"/);
  });

  it("renders inside the shared wrapper (section header + Clock icon)", () => {
    // The section carries the H2 heading + Clock icon.
    const secIdx = SRC.indexOf(
      'data-testid="customer-detail-comm-timeline-section"');
    expect(secIdx).toBeGreaterThan(-1);
    const slice = SRC.slice(secIdx, secIdx + 600);
    expect(slice).toMatch(/Communication Timeline/);
    expect(slice).toMatch(/<Clock\s+size=\{16\}/);
    expect(slice).toMatch(/variant="admin"/);
    expect(slice).toMatch(/customerId=\{id\}/);
  });

  it("has exactly one CommunicationTimeline mount in the file", () => {
    const occurrences = SRC.match(/<CommunicationTimeline/g) || [];
    expect(occurrences.length).toBe(1);
  });
});
