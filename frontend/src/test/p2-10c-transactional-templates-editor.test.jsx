/**
 * P2 #10c · Feb-2026 — TransactionalTemplates admin editor UI.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";


const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), post: (...a) => apiPost(...a),
          patch: (...a) => apiPatch(...a) },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));


import TransactionalTemplates from "@/pages/settings/TransactionalTemplates";


const _REG = {
  templates: [
    {
      code: "welcome_on_first_accept_email",
      channel: "email",
      required_tags: ["company_name", "customer_first_name", "portal_url"],
      optional_tags: ["company_phone"],
      description: "Welcome email on first-accept.",
    },
    {
      code: "quote_decline_admin_sms",
      channel: "sms",
      required_tags: ["customer_name", "quote_short_id"],
      optional_tags: [],
      description: "SMS to admin on quote decline.",
    },
  ],
};


beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPatch.mockReset();
});


describe("P2 #10c · TransactionalTemplates editor", () => {
  it("Case 1 — list renders a row per registry slug with testids", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/marketing/transactional-registry") return Promise.resolve(_REG);
      if (path.startsWith("/marketing/templates")) return Promise.resolve({ items: [] });
      return Promise.reject(new Error("unexpected " + path));
    });
    render(<TransactionalTemplates />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(screen.getByTestId("transactional-templates-list")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-row-welcome_on_first_accept_email")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-row-quote_decline_admin_sms")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-edit-btn-welcome_on_first_accept_email")).toBeTruthy();
  });

  it("Case 2 — edit flow surfaces subject + body inputs + docs panel", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/marketing/transactional-registry") return Promise.resolve(_REG);
      if (path.startsWith("/marketing/templates")) return Promise.resolve({ items: [] });
      return Promise.reject(new Error("unexpected " + path));
    });
    render(<TransactionalTemplates />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("transactional-template-edit-btn-welcome_on_first_accept_email"));
    expect(screen.getByTestId("transactional-template-editor")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-subject-input")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-body-input")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-docs-panel")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-save-btn")).toBeTruthy();
    expect(screen.getByTestId("transactional-template-cancel-btn")).toBeTruthy();
  });

  it("Case 3 — save calls POST (create) with required merge tags", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/marketing/transactional-registry") return Promise.resolve(_REG);
      if (path.startsWith("/marketing/templates")) return Promise.resolve({ items: [] });
      return Promise.reject(new Error("unexpected " + path));
    });
    apiPost.mockResolvedValue({ ok: true });
    render(<TransactionalTemplates />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("transactional-template-edit-btn-welcome_on_first_accept_email"));
    fireEvent.change(screen.getByTestId("transactional-template-subject-input"),
      { target: { value: "Welcome {{customer_first_name}}" } });
    fireEvent.change(screen.getByTestId("transactional-template-body-input"),
      { target: { value: "Hi {{customer_first_name}}, {{company_name}} at {{portal_url}}" } });
    fireEvent.click(screen.getByTestId("transactional-template-save-btn"));
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const call = apiPost.mock.calls.find((c) => c[0] === "/marketing/templates");
    expect(call).toBeTruthy();
    expect(call[1].code).toBe("welcome_on_first_accept_email");
    expect(call[1].body).toContain("{{customer_first_name}}");
  });

  it("Case 4 — save BLOCKED when required merge tags missing (client-side)", async () => {
    const { toast } = await import("sonner");
    apiGet.mockImplementation((path) => {
      if (path === "/marketing/transactional-registry") return Promise.resolve(_REG);
      if (path.startsWith("/marketing/templates")) return Promise.resolve({ items: [] });
      return Promise.reject(new Error("unexpected " + path));
    });
    render(<TransactionalTemplates />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("transactional-template-edit-btn-welcome_on_first_accept_email"));
    fireEvent.change(screen.getByTestId("transactional-template-subject-input"),
      { target: { value: "Welcome" } });
    fireEvent.change(screen.getByTestId("transactional-template-body-input"),
      { target: { value: "No tags here" } });
    fireEvent.click(screen.getByTestId("transactional-template-save-btn"));
    // No POST was called — client validator fail-closed.
    expect(apiPost).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("Case 5 — reset button visible only when override is active", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/marketing/transactional-registry") return Promise.resolve(_REG);
      if (path.startsWith("/marketing/templates")) return Promise.resolve({
        items: [{
          id: "tpl-abc", code: "welcome_on_first_accept_email", active: true,
          subject: "Hi {{customer_first_name}}", body: "{{company_name}} {{portal_url}}",
        }],
      });
      return Promise.reject(new Error("unexpected " + path));
    });
    render(<TransactionalTemplates />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    // Welcome row has an active override — reset button visible.
    expect(screen.getByTestId("transactional-template-reset-btn-welcome_on_first_accept_email")).toBeTruthy();
    // Decline SMS has no override — reset button NOT rendered.
    expect(screen.queryByTestId("transactional-template-reset-btn-quote_decline_admin_sms")).toBeNull();
  });
});
