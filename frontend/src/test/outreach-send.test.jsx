/**
 * Phase SEO-B · Feb-2026 — Send Email flow vitest.
 *
 * Verifies:
 *   1. Detail drawer surfaces a "Send email" button.
 *   2. Clicking it opens the template picker modal.
 *   3. Selecting a template renders the preview with variables filled
 *      in from the prospect row.
 *   4. Send button fires POST /outreach/prospects/{id}/send with the
 *      template_id.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _prospect = {
  id: "p-send", tenant_id: "T", domain: "target.com",
  status: "pending",
  contact_name: "Jamie", contact_email: "jamie@target.com",
  contact_role: "editor",
  our_page_url: "https://ours.com/best-pools",
  desired_anchor: "pool service phoenix",
  tags: ["editor"], notes: "",
  messages: [],
  updated_at: "2026-02-14T09:00:00Z",
};

const _templates = [
  { id: "t1", name: "Intro pitch",
    subject: "Quick question about {{their_domain}}",
    body_html: "Hi {{contact_name}}, would you consider linking to "
               + "{{our_page_url}} with anchor {{desired_anchor}}?",
    variables: ["contact_name", "their_domain",
                 "our_page_url", "desired_anchor"],
    archived: false },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/outreach/prospects?"))
        return { items: [_prospect], total: 1, limit: 500, offset: 0 };
      if (path === "/outreach/pipeline")
        return { pending: 1, contacted: 0, replied: 0,
                 link_placed: 0, declined: 0, unsubscribed: 0, total: 1 };
      if (path.startsWith("/outreach/templates"))
        return { items: _templates, total: 1 };
      if (path.startsWith("/outreach/prospects/p-send"))
        return _prospect;
      return {};
    }),
    post: vi.fn(async (path) => {
      if (path.endsWith("/send")) {
        return { message: { id: "m1", subject_rendered: "sent",
                             body_rendered: "sent" },
                 status: "sent" };
      }
      return {};
    }),
    patch: vi.fn(async () => ({})),
    del: vi.fn(async () => ({})),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}

import ProspectsKanbanPage from "@/pages/admin/outreach/ProspectsKanbanPage";
import { api } from "@/api";

describe("Outreach send flow", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("Send-email button surfaces in the detail drawer, opens modal with template preview, and fires POST /send",
     async () => {
    render(<MemoryRouter><ProspectsKanbanPage /></MemoryRouter>);
    // Open detail drawer via card's "Open" button.
    await screen.findByTestId("prospect-card-p-send");
    fireEvent.click(screen.getByTestId("prospect-open-p-send"));
    // Drawer + "Send email" button visible.
    const sendBtn = await screen.findByTestId("detail-send-email");
    expect(sendBtn).toBeInTheDocument();
    fireEvent.click(sendBtn);
    // Modal renders with template dropdown.
    const select = await screen.findByTestId("send-email-template-select");
    fireEvent.change(select, { target: { value: "t1" } });
    // Preview renders with variables substituted.
    await waitFor(() => {
      const subject = screen.getByTestId("send-email-preview-subject");
      const body = screen.getByTestId("send-email-preview-body");
      expect(subject.textContent).toContain("target.com");
      expect(body.textContent).toContain("Jamie");
      expect(body.textContent).toContain("https://ours.com/best-pools");
      expect(body.textContent).toContain("pool service phoenix");
    });
    // Send fires POST.
    fireEvent.click(screen.getByTestId("send-email-submit"));
    await waitFor(() => {
      const calls = api.post.mock.calls
        .filter((c) => typeof c[0] === "string" && c[0].endsWith("/send"));
      expect(calls.length).toBe(1);
      expect(calls[0][0]).toBe("/outreach/prospects/p-send/send");
      expect(calls[0][1].template_id).toBe("t1");
    });
  });
});
