// P0c Stage 2 · S2-2 · Vitest coverage for StripeWebhookDiagnostic panel.
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Mock the api module BEFORE importing the component.
vi.mock("../api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    del: vi.fn(),
    request: vi.fn(),
  },
}));

import { api } from "../api";
import { StripeWebhookDiagnostic } from "../components/admin/StripeWebhookDiagnostic.jsx";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const _HEALTHY_LIVE_PAYLOAD = {
  generated_at: "2026-10-12T03:21:39.421355+00:00",
  registered_webhook_paths: [
    "/api/payments/stripe/webhook",
    "/api/stripe/webhook",
  ],
  config: {
    mode: "live",
    app_env: "production",
    api_key_configured: true,
    api_key_prefix: "sk_live_…",
    api_key_length: 107,
    webhook_secret_configured: true,
    webhook_secret_prefix: "whsec_SJ…",
    webhook_secret_length: 38,
    mode_match: "live",
    issues: [],
  },
  recent_events_total: 1,
  recent_events: [
    {
      event_id: "evt_abc",
      event_type: "payment_intent.succeeded",
      received_at: "2026-10-12T03:20:00Z",
      status: "handled",
      retry_count: 0,
      first_handled_at: "2026-10-12T03:20:01Z",
      last_error: null,
      tenant_id_hint: null,
    },
  ],
  recent_dead_letters_total: 0,
  recent_dead_letters: [],
  suggested_next_action:
    "Configuration looks healthy. If webhooks still fail from the Stripe Dashboard, verify the Dashboard endpoint URL exactly matches one of the paths in registered_webhook_paths below.",
};

const _MISMATCH_PAYLOAD = {
  generated_at: "2026-10-12T03:21:39.421355+00:00",
  registered_webhook_paths: [
    "/api/payments/stripe/webhook",
    "/api/stripe/webhook",
  ],
  config: {
    mode: "live",
    app_env: "production",
    api_key_configured: true,
    api_key_prefix: "sk_test_…",
    api_key_length: 107,
    webhook_secret_configured: true,
    webhook_secret_prefix: "whsec_XX…",
    webhook_secret_length: 38,
    mode_match: "mismatch",
    issues: [
      {
        severity: "error",
        code: "api_key_test_in_live_mode",
        message:
          "Stripe API key is sk_test_* but STRIPE_MODE=live. Rotate STRIPE_SECRET_KEY_LIVE to a sk_live_* key.",
      },
    ],
  },
  recent_events_total: 0,
  recent_events: [],
  recent_dead_letters_total: 2,
  recent_dead_letters: [
    {
      event_id: "evt_dl_1",
      event_type: "invoice.paid",
      first_failed_at: "2026-10-11T20:00:00Z",
      last_retry_at: "2026-10-11T22:00:00Z",
      error_class: "SignatureVerificationError",
      error_message: "No signatures found matching the expected signature for payload",
      retry_count_after_first: 3,
      tenant_id_hint: null,
    },
    {
      event_id: "evt_dl_2",
      event_type: "charge.succeeded",
      first_failed_at: "2026-10-11T18:00:00Z",
      last_retry_at: "2026-10-11T19:00:00Z",
      error_class: "RuntimeError",
      error_message: "handler explosion",
      retry_count_after_first: 1,
      tenant_id_hint: "t-abc",
    },
  ],
  suggested_next_action:
    "Rotate the Stripe secret-key / webhook-secret pair so BOTH match STRIPE_MODE. Copy the current signing secret from the Stripe Dashboard → Developers → Webhooks → <your endpoint> → Signing secret, and store it in STRIPE_WEBHOOK_SECRET_LIVE (or _TEST) matching STRIPE_MODE.",
};

describe("StripeWebhookDiagnostic", () => {
  it("renders a healthy LIVE OK badge and both registered paths", async () => {
    api.get.mockResolvedValueOnce(_HEALTHY_LIVE_PAYLOAD);
    render(<StripeWebhookDiagnostic />);

    await waitFor(() => {
      expect(screen.getByTestId("stripe-webhook-diagnostic")).toBeInTheDocument();
    });
    expect(screen.getByTestId("stripe-diag-mode-match")).toHaveTextContent("LIVE OK");
    expect(screen.getByTestId("stripe-diag-mode")).toHaveTextContent("live");
    // Both URLs listed.
    const paths = screen.getByTestId("stripe-diag-paths");
    expect(paths).toHaveTextContent("/api/payments/stripe/webhook");
    expect(paths).toHaveTextContent("/api/stripe/webhook");
    // Secret appears redacted (prefix + length), not raw.
    expect(screen.getByTestId("stripe-diag-webhook-secret")).toHaveTextContent(
      "whsec_SJ…",
    );
    expect(screen.getByTestId("stripe-diag-webhook-secret")).toHaveTextContent("38 chars");
  });

  it("renders MISMATCH badge + the api_key_test_in_live_mode issue + the suggested action", async () => {
    api.get.mockResolvedValueOnce(_MISMATCH_PAYLOAD);
    render(<StripeWebhookDiagnostic />);

    await waitFor(() => {
      expect(screen.getByTestId("stripe-webhook-diagnostic")).toBeInTheDocument();
    });
    expect(screen.getByTestId("stripe-diag-mode-match")).toHaveTextContent("MISMATCH");

    // Issue is listed with its code tag.
    expect(screen.getByTestId("stripe-diag-issue-api_key_test_in_live_mode"))
      .toBeInTheDocument();

    // Suggestion visible + mentions STRIPE_WEBHOOK_SECRET_LIVE.
    const sug = screen.getByTestId("stripe-diag-suggestion");
    expect(sug).toHaveTextContent(/rotate/i);
    expect(sug).toHaveTextContent(/STRIPE_WEBHOOK_SECRET/);
  });

  it("renders the dead-letter panel with error_class + error_message", async () => {
    api.get.mockResolvedValueOnce(_MISMATCH_PAYLOAD);
    render(<StripeWebhookDiagnostic />);
    await waitFor(() => {
      expect(screen.getByTestId("stripe-diag-dead-letters")).toBeInTheDocument();
    });
    expect(screen.getByTestId("stripe-diag-dl-evt_dl_1")).toHaveTextContent(
      "SignatureVerificationError",
    );
    expect(screen.getByTestId("stripe-diag-dl-evt_dl_2")).toHaveTextContent(
      "RuntimeError",
    );
  });

  it("renders a loading state before the fetch resolves", async () => {
    api.get.mockReturnValue(new Promise(() => { /* never resolves */ }));
    render(<StripeWebhookDiagnostic />);
    expect(screen.getByTestId("stripe-webhook-diagnostic-loading")).toBeInTheDocument();
  });

  it("renders an error state on API failure + a retry button", async () => {
    api.get.mockRejectedValueOnce(new Error("boom"));
    render(<StripeWebhookDiagnostic />);
    await waitFor(() => {
      expect(screen.getByTestId("stripe-webhook-diagnostic-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("stripe-webhook-diagnostic-retry")).toBeInTheDocument();
  });

  it("renders the no-events message when recent_events_total is 0", async () => {
    const empty = {
      ..._HEALTHY_LIVE_PAYLOAD,
      recent_events_total: 0,
      recent_events: [],
    };
    api.get.mockResolvedValueOnce(empty);
    render(<StripeWebhookDiagnostic />);
    await waitFor(() => {
      expect(screen.getByTestId("stripe-diag-no-events")).toBeInTheDocument();
    });
    expect(screen.getByTestId("stripe-diag-no-events")).toHaveTextContent(
      /no webhook events/i,
    );
  });

  it("does not render secrets in raw form (prefix only + length)", async () => {
    api.get.mockResolvedValueOnce(_HEALTHY_LIVE_PAYLOAD);
    const { container } = render(<StripeWebhookDiagnostic />);
    await waitFor(() => {
      expect(screen.getByTestId("stripe-webhook-diagnostic")).toBeInTheDocument();
    });
    const txt = container.textContent || "";
    // The healthy payload's full secret is not present in the component
    // (backend returned only the prefix). This proves the panel never
    // tries to reconstitute a secret client-side.
    expect(txt).not.toMatch(/whsec_SJ[a-zA-Z0-9]{30,}/);
  });
});
