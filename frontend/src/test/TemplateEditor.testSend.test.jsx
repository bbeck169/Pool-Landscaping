/**
 * SAFE-SEND-B · Feb-2026 — Test-send flow tests.
 *
 * Locks ``MarketingTemplatesAdmin::testSend()``:
 *
 *   1. Clicking "Send" POSTs with ``context: "test"`` in the body.
 *   2. On 200 ``ok=true`` → success toast contains "Sent to admin".
 *   3. On HTTP 400 with ``error_code: "invalid_comms_context"`` →
 *      error toast contains "context spoofing detected".
 *   4. On 200 with ``provider_status: "skipped_no_redirect_target"``
 *      → warning toast contains "Redirect target missing".
 *   5. Existing rate-limit / generic-failure paths still work.
 *
 * The page mounts under ``/marketing/templates/:id`` — we mock the
 * router param, the sonner toast primitive, and the ``api`` client.
 * TipTap + MergeTagPalette + MediaLibraryPicker are heavy — we
 * stub the entire ``TemplateEditor`` component to a plain
 * ``textarea`` so the page renders without loading the rich-text
 * pipeline in the test harness.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";


// ═══════════════════════════════════════════════════════════════
// Global mocks
// ═══════════════════════════════════════════════════════════════
const { _toastMock } = vi.hoisted(() => ({
  _toastMock: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));
vi.mock("sonner", () => ({ toast: _toastMock }));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

// Confirm-dialog primitive — auto-accept.  The page uses
// ``mustConfirm`` directly (not the hook variant).
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: async () => true,
  MustConfirmProvider: ({ children }) => <>{children}</>,
}));

// TipTap-based rich editor is heavy; stub to a textarea so the
// page renders without pulling the editor pipeline.
vi.mock("@/components/marketing/TemplateEditor", () => ({
  TemplateEditor: ({ value, onChange }) => (
    <textarea
      data-testid="template-editor-content"
      value={value || ""}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
  computeSmsSegments: () => ({ segments: 1, characters: 0, encoding: "GSM-7" }),
}));
vi.mock("@/components/marketing/MergeTagPalette", () => ({
  MergeTagPalette: () => null,
}));
vi.mock("@/components/marketing/MediaLibraryPicker", () => ({
  MediaLibraryPicker: () => null,
}));


// Row fixtures ─────────────────────────────────────────────────
function _emailTemplate(overrides = {}) {
  return {
    id: "tpl-1", tenant_id: "t-x", channel: "email",
    kind: "campaign",
    name: "Welcome",
    subject: "Hi {{ FIRST_NAME }}",
    body: "<p>Welcome</p>",
    status: "draft",
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}


async function _mountAdminPage() {
  const mod = await import("@/pages/marketing/MarketingTemplatesAdmin");
  const Page = mod.MarketingTemplateDetailPage;
  return render(
    <MemoryRouter initialEntries={["/marketing/templates/tpl-1"]}>
      <Routes>
        <Route path="/marketing/templates/:id" element={<Page />} />
      </Routes>
    </MemoryRouter>,
  );
}


// ═══════════════════════════════════════════════════════════════
// Test-send POST payload — always carries context: "test"
// ═══════════════════════════════════════════════════════════════
describe("SAFE-SEND-B · TemplateEditor test-send", () => {
  beforeEach(() => {
    _toastMock.success.mockClear();
    _toastMock.error.mockClear();
    _toastMock.warning.mockClear();
    _apiMock.get.mockReset();
    _apiMock.post.mockReset();
  });

  async function _openPage() {
    _apiMock.get.mockImplementation(async (path) => {
      if (path.startsWith("/marketing/templates/tpl-1")) {
        return _emailTemplate();
      }
      if (path.startsWith("/marketing/templates/") && path.endsWith("/preview")) {
        return { subject: "Preview subject", body: "<p>preview</p>" };
      }
      return {};
    });
    // ``/preview`` is a POST from the page — let it pass through.
    _apiMock.post.mockImplementation(async (path) => {
      if (path === "/marketing/templates/tpl-1/preview") {
        return { subject: "Preview subject", body: "<p>preview</p>" };
      }
      // The test-send POST is the one we set per-test.
      throw new Error(`Unexpected POST in fixture: ${path}`);
    });
    await _mountAdminPage();
    // Wait for the template to load — the test-send button appears
    // only after the row is fetched.
    await waitFor(() => {
      expect(screen.getByTestId("template-testsend-btn")).toBeInTheDocument();
    });
  }

  it("POSTs with context: 'test' in the body", async () => {
    await _openPage();
    // Rebind ``post`` — allow preview through, capture test-send.
    _apiMock.post.mockImplementation(async (path, body) => {
      if (path === "/marketing/templates/tpl-1/preview") {
        return { subject: "s", body: "b" };
      }
      return {
        ok: true, channel: "email", recipient: body?.to,
        provider: "resend", provider_status: "sent",
        provider_response_id: "resend-abc",
      };
    });
    fireEvent.change(screen.getByTestId("template-testsend-to"), {
      target: { value: "admin@t.test" },
    });
    fireEvent.click(screen.getByTestId("template-testsend-btn"));
    await waitFor(() => {
      const calls = _apiMock.post.mock.calls
        .filter((c) => c[0] === "/marketing/templates/tpl-1/test-send");
      expect(calls.length).toBe(1);
      const [, body] = calls[0];
      expect(body).toMatchObject({
        to: "admin@t.test",
        context: "test",
      });
    });
  });

  it("success toast fires on 200 ok=true", async () => {
    await _openPage();
    _apiMock.post.mockImplementation(async (path) => {
      if (path.endsWith("/preview")) return { subject: "s", body: "b" };
      return {
        ok: true, channel: "email", provider: "resend",
        provider_status: "sent",
      };
    });
    fireEvent.change(screen.getByTestId("template-testsend-to"), {
      target: { value: "admin@t.test" },
    });
    fireEvent.click(screen.getByTestId("template-testsend-btn"));
    await waitFor(() => {
      const success = _toastMock.success.mock.calls.map((c) => c[0]);
      expect(success.some(
        (m) => typeof m === "string" && m.includes("Sent to admin"),
      )).toBe(true);
      expect(success.some(
        (m) => typeof m === "string" && m.includes("context: TEST"),
      )).toBe(true);
    });
  });

  it("shows spoofing-detected toast on 400 invalid_comms_context", async () => {
    await _openPage();
    _apiMock.post.mockImplementation(async (path) => {
      if (path.endsWith("/preview")) return { subject: "s", body: "b" };
      // Simulate the SAFE-SEND-A 400 envelope from api.js.
      const err = new Error("context=SYSTEM|AGENT is server-controlled");
      err.status = 400;
      err.data = {
        error_code: "invalid_comms_context",
        detail: "context=SYSTEM|AGENT is server-controlled",
        supplied: "system",
      };
      throw err;
    });
    fireEvent.change(screen.getByTestId("template-testsend-to"), {
      target: { value: "admin@t.test" },
    });
    fireEvent.click(screen.getByTestId("template-testsend-btn"));
    await waitFor(() => {
      const errs = _toastMock.error.mock.calls.map((c) => c[0]);
      expect(errs.some(
        (m) => typeof m === "string" && m.includes("context spoofing detected"),
      )).toBe(true);
    });
  });

  it("shows redirect-target-missing warning on skipped_no_redirect_target", async () => {
    await _openPage();
    _apiMock.post.mockImplementation(async (path) => {
      if (path.endsWith("/preview")) return { subject: "s", body: "b" };
      // SAFE-SEND-A.1 suppression marker — 200 response envelope
      // carries the marker on ``provider_status``.
      return {
        ok: false, channel: "email",
        provider: "resend",
        provider_status: "skipped_no_redirect_target",
        safe_send_context: "test",
        original_to: "admin@t.test",
      };
    });
    fireEvent.change(screen.getByTestId("template-testsend-to"), {
      target: { value: "admin@t.test" },
    });
    fireEvent.click(screen.getByTestId("template-testsend-btn"));
    await waitFor(() => {
      const warns = _toastMock.warning.mock.calls.map((c) => c[0]);
      expect(warns.some(
        (m) => typeof m === "string" && m.includes("Redirect target missing"),
      )).toBe(true);
      expect(warns.some(
        (m) => typeof m === "string" && m.includes("business_card.email"),
      )).toBe(true);
    });
    // Non-blocking: success toast must NOT fire on suppression.
    expect(_toastMock.success).not.toHaveBeenCalled();
  });

  it("preserves existing rate-limit copy on 429", async () => {
    await _openPage();
    _apiMock.post.mockImplementation(async (path) => {
      if (path.endsWith("/preview")) return { subject: "s", body: "b" };
      const err = new Error("429 too many requests");
      err.status = 429;
      throw err;
    });
    fireEvent.change(screen.getByTestId("template-testsend-to"), {
      target: { value: "admin@t.test" },
    });
    fireEvent.click(screen.getByTestId("template-testsend-btn"));
    await waitFor(() => {
      const errs = _toastMock.error.mock.calls.map((c) => c[0]);
      expect(errs.some(
        (m) => typeof m === "string" && m.includes("Rate-limited"),
      )).toBe(true);
    });
  });
});
