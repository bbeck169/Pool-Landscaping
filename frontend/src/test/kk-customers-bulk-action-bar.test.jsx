/**
 * Ticket KK · Feb-2026 — Customers list bulk action bar + MassTextModal
 * behavioural + source-shape regression locks.
 *
 * Covers:
 *   1. MassTextModal mount — renders, lists templates from the
 *      ``/marketing/templates/sms`` endpoint, template pick fills
 *      the textarea, char + segment counter renders, recipient
 *      count surfaces, Send→Confirm two-step pattern (destructive
 *      red), confirm fires ``POST /customers/bulk-sms`` with the
 *      correct payload, success toast surfaces the opt-out
 *      breakdown.
 *   2. Source-shape locks on CustomersList.jsx — the Mass Text
 *      action entry is present, the Reassign Owner action entry +
 *      ``doBulkOwner`` handler are REMOVED, the modal is mounted,
 *      the LL inert placeholder slot is present in MassTextModal.
 *   3. Green-gradient parity — the modal's primary Send button is
 *      rendered via the ui-kit ``<Button variant="primary">`` which
 *      IS the "+ New Customer" button's own primitive (navy→green
 *      ``gradients.navyToGreen`` theme token). Grep-locked via
 *      source string so a future refactor can't quietly swap it
 *      for a bespoke button.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, cleanup, waitFor,
} from "@testing-library/react";


// ── API mock ──────────────────────────────────────────────────
const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: apiGetMock, post: apiPostMock },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

// Toast noop so we can observe call shapes without surface churn.
const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: Object.assign(
    (...args) => toastSuccess(...args),
    { success: toastSuccess, error: toastError },
  ),
}));

import MassTextModal from "@/components/customers/MassTextModal";


const _TEMPLATES = [
  { id: "tpl-reminder", name: "Weekly reminder",
    body: "Hi {{first_name}}, your service is scheduled for tomorrow." },
  { id: "tpl-promo", name: "Spring promo",
    body: "Spring open-up deal — book this week to save 20%." },
];


beforeEach(() => {
  apiGetMock.mockReset();
  apiPostMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  // Default: templates endpoint returns the fixture array.
  apiGetMock.mockImplementation((p) => {
    if (p === "/marketing/templates/sms") return Promise.resolve(_TEMPLATES);
    return Promise.resolve(null);
  });
});

afterEach(() => cleanup());


// ═══════════════════════════════════════════════════════════════
// 1. MassTextModal mount behaviour
// ═══════════════════════════════════════════════════════════════
describe("Ticket KK · MassTextModal", () => {
  it("renders with recipient count + rewrite placeholder + segment counter", async () => {
    render(
      <MassTextModal
        open
        customerIds={["c-1", "c-2", "c-3"]}
        onClose={vi.fn()}
        onSent={vi.fn()}
      />,
    );
    expect(screen.getByTestId("mass-text-modal")).toBeTruthy();
    expect(screen.getByTestId("mass-text-recipient-count").textContent)
      .toContain("Sending to 3 customers");
    // Ticket KK reserved a rewrite slot (``mass-text-rewrite-slot``);
    // Ticket LL swapped the inert placeholder for the live
    // ``<AiRewriteButton>`` with testid ``mass-text-rewrite-btn``.
    // The slot container remains for layout stability.
    expect(screen.getByTestId("mass-text-rewrite-slot")).toBeTruthy();
    expect(screen.getByTestId("mass-text-rewrite-btn")).toBeTruthy();
    // Segment counter — starts at 0 chars.
    expect(screen.getByTestId("mass-text-segments").textContent)
      .toMatch(/0 chars/);
  });

  it("lists SMS templates from /marketing/templates/sms and fills the textarea on pick", async () => {
    render(
      <MassTextModal
        open
        customerIds={["c-1"]}
        onClose={vi.fn()}
        onSent={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("mass-text-template-option-tpl-reminder")).toBeTruthy();
    });
    expect(screen.getByTestId("mass-text-template-option-tpl-promo")).toBeTruthy();
    // Pick the reminder template — textarea fills with the body.
    const picker = screen.getByTestId("mass-text-template-picker");
    fireEvent.change(picker, { target: { value: "tpl-reminder" } });
    const body = screen.getByTestId("mass-text-body");
    expect(body.value).toContain("Hi {{first_name}}");
    // Segment counter updates after a template fill.
    expect(screen.getByTestId("mass-text-segments").textContent)
      .toMatch(/\d+ chars/);
  });

  it("Send-to-N shows a destructive confirm button before firing the API", async () => {
    render(
      <MassTextModal
        open
        customerIds={["c-1", "c-2"]}
        onClose={vi.fn()}
        onSent={vi.fn()}
      />,
    );
    const body = screen.getByTestId("mass-text-body");
    fireEvent.change(body, { target: { value: "Hello mass text" } });
    const sendBtn = screen.getByTestId("mass-text-send");
    fireEvent.click(sendBtn);
    // Second click arms the confirm — a NEW testid surfaces.
    const confirm = screen.getByTestId("mass-text-send-confirm");
    expect(confirm.textContent).toMatch(/Yes, send to 2/);
    // Confirm banner surfaces explaining opt-outs are skipped.
    expect(screen.getByTestId("mass-text-confirm-banner").textContent)
      .toMatch(/opted-out and no-phone customers are skipped/i);
  });

  it("fires POST /customers/bulk-sms with the correct payload on confirm", async () => {
    apiPostMock.mockResolvedValue({
      batch_id: "b-1", selected_count: 2, resolved_count: 2,
      queued: 1, skipped_opt_out: 1, skipped_no_phone: 0,
      skipped_cross_tenant: 0, status: "running",
    });
    const onSent = vi.fn();
    const onClose = vi.fn();
    render(
      <MassTextModal
        open
        customerIds={["c-1", "c-2"]}
        onClose={onClose}
        onSent={onSent}
      />,
    );
    // Compose + pick template.
    await waitFor(() => {
      expect(screen.getByTestId("mass-text-template-option-tpl-promo")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("mass-text-template-picker"),
                      { target: { value: "tpl-promo" } });
    // Edit the message so the override + template_id both land.
    fireEvent.change(screen.getByTestId("mass-text-body"),
                      { target: { value: "Custom override message" } });
    // Arm + confirm.
    fireEvent.click(screen.getByTestId("mass-text-send"));
    fireEvent.click(screen.getByTestId("mass-text-send-confirm"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalled());
    expect(apiPostMock).toHaveBeenCalledWith("/customers/bulk-sms", {
      customer_ids: ["c-1", "c-2"],
      message: "Custom override message",
      template_id: "tpl-promo",
    });
    // Success toast + onSent + onClose fire.
    await waitFor(() => expect(onSent).toHaveBeenCalled());
    expect(toastSuccess).toHaveBeenCalled();
    expect(toastSuccess.mock.calls[0][0]).toMatch(/Mass Text queued to 1 customer/);
    const toastOpts = toastSuccess.mock.calls[0][1];
    expect(toastOpts && toastOpts.description).toMatch(/1 opted-out/);
    expect(onClose).toHaveBeenCalled();
  });

  it("surfaces a friendly error when the backend returns 429 RATE_LIMITED", async () => {
    apiPostMock.mockRejectedValue({
      detail: { code: "RATE_LIMITED" },
    });
    render(
      <MassTextModal
        open
        customerIds={["c-1"]}
        onClose={vi.fn()}
        onSent={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId("mass-text-body"),
                      { target: { value: "429 case" } });
    fireEvent.click(screen.getByTestId("mass-text-send"));
    fireEvent.click(screen.getByTestId("mass-text-send-confirm"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0])
      .toMatch(/wait a few minutes/i);
  });
});


// ═══════════════════════════════════════════════════════════════
// 2. CustomersList source-shape locks
// ═══════════════════════════════════════════════════════════════
const CUSTOMERS_LIST_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);

describe("Ticket KK · CustomersList source-shape locks", () => {
  it("imports MassTextModal", () => {
    expect(CUSTOMERS_LIST_SRC).toMatch(
      /import MassTextModal from "@\/components\/customers\/MassTextModal"/,
    );
  });

  it("adds a `mass-text` action entry to the shared BulkActionBar", () => {
    expect(CUSTOMERS_LIST_SRC).toMatch(/key:\s*"mass-text",\s*label:\s*"Mass Text"/);
  });

  it("mounts the MassTextModal with the current selection", () => {
    expect(CUSTOMERS_LIST_SRC).toMatch(/<MassTextModal[\s\S]{0,200}?open=\{massTextOpen\}/);
    expect(CUSTOMERS_LIST_SRC).toMatch(
      /<MassTextModal[\s\S]{0,400}?customerIds=\{Array\.from\(selected\)\}/,
    );
  });

  it("removes the Reassign Owner action entry from the bulk action bar", () => {
    expect(CUSTOMERS_LIST_SRC).not.toMatch(
      /key:\s*"owner",\s*label:\s*"Reassign owner"/,
    );
  });

  it("removes the doBulkOwner handler", () => {
    expect(CUSTOMERS_LIST_SRC).not.toMatch(/const doBulkOwner\s*=\s*async/);
  });
});


// ═══════════════════════════════════════════════════════════════
// 3. Green-gradient parity — MassTextModal Send button is the
//    ui-kit <Button variant="primary"> primitive (which IS the
//    "+ New Customer" button's own primitive, navy→green theme
//    token).
// ═══════════════════════════════════════════════════════════════
const MASS_TEXT_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/components/customers/MassTextModal.jsx"),
  "utf-8",
);

describe("Ticket KK · green-gradient parity", () => {
  it("imports the ui-kit Button primitive (the + New Customer button's primitive)", () => {
    expect(MASS_TEXT_SRC).toMatch(
      /import \{[\s\S]*?Button[\s\S]*?\} from "@\/components\/ui-kit"/,
    );
  });

  it("renders the pre-confirm Send CTA via <Button variant=\"primary\">", () => {
    // The pre-confirm CTA (``mass-text-send``) must be a ui-kit
    // Button in primary variant so it picks up the global
    // gradients.navyToGreen token.  Grep-locked so a future
    // refactor can't quietly swap it for a bespoke bg-gradient.
    expect(MASS_TEXT_SRC).toMatch(
      /<Button[\s\S]{0,300}?variant="primary"[\s\S]{0,600}?testid="mass-text-send"/,
    );
  });

  it("hosts the LL <AiRewriteButton> inside the rewrite slot (post Ticket LL swap)", () => {
    expect(MASS_TEXT_SRC).toMatch(/data-testid="mass-text-rewrite-slot"/);
    // Ticket LL replaced KK's inert placeholder with the live
    // ``<AiRewriteButton>``.  The slot container remains for
    // layout stability; the inert ``mass-text-rewrite-placeholder``
    // testid is retired.
    expect(MASS_TEXT_SRC).toMatch(/<AiRewriteButton[\s\S]{0,500}?dataTestid="mass-text-rewrite-btn"/);
    expect(MASS_TEXT_SRC).not.toMatch(/mass-text-rewrite-placeholder/);
  });
});
