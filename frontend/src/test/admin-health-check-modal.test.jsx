/**
 * Phase I3 · Feb-2026 — HealthCheckCard modal.
 *
 * Interaction test — render the card, click the trigger, verify the
 * modal opens with a color-coded verdict banner, per-check rows,
 * recommendations, and a working Copy JSON button (clipboard mocked).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args) },
}));
vi.mock("../../theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#fafafa", border: "#eee",
    muted: "#666", onSurface: "#000", brand: "#0891B2",
    brandTertiary: "#E0F2FE",
  },
}));

import HealthCheckCard from "@/components/admin/HealthCheckCard";


const SAMPLE_GO_WITH_WARNINGS = {
  overall_verdict: "GO_WITH_WARNINGS",
  tenant_id: "aquaterra",
  timestamp: "2026-02-14T09:00:00+00:00",
  app_version: "dev",
  checks: [
    {name: "boot_state", status: "ok", details: {complete: true, dangling_refs_total: 0}, duration_ms: 3},
    {name: "mongo_ping", status: "ok", details: {timeout_s: 0.5}, duration_ms: 8},
    {name: "required_migrations", status: "ok", details: {applied: ["perf_customers_v1"]}, duration_ms: 4},
    {name: "optional_migrations", status: "warn", details: {pending: ["perf_customers_v2"], pending_count: 1}, duration_ms: 5},
    {name: "hotpath_smoke", status: "ok", details: {customers_list: {status: "ok"}}, duration_ms: 12},
    {name: "comms_gate", status: "ok", details: {module: "dispatch_guard"}, duration_ms: 1},
    {name: "rc_sms_from_number", status: "ok", details: {resolved: true, length: 12}, duration_ms: 2},
    {name: "scheduler", status: "ok", details: {running: true, job_count: 5}, duration_ms: 1},
    {name: "env_sanity", status: "warn", details: {missing: [], empty: ["STRIPE_SECRET_KEY"]}, duration_ms: 0},
    {name: "feature_gates", status: "ok", details: {values: {SOSHIE_MODERATION_ENABLED: "(unset)"}, notes: []}, duration_ms: 0},
  ],
  summary: {checks_total: 10, ok: 8, warn: 2, fail: 0},
  recommendations: [
    "1 non-required migration(s) pending: perf_customers_v2. Safe to GO.",
    "Env vars present but empty: STRIPE_SECRET_KEY. Treated as unset.",
  ],
};

const SAMPLE_NO_GO = {
  ...SAMPLE_GO_WITH_WARNINGS,
  overall_verdict: "NO_GO",
  summary: {checks_total: 10, ok: 7, warn: 2, fail: 1},
  checks: [
    ...SAMPLE_GO_WITH_WARNINGS.checks.slice(0, 2),
    {name: "required_migrations", status: "fail", details: {missing: ["perf_customers_v1"]}, duration_ms: 4},
    ...SAMPLE_GO_WITH_WARNINGS.checks.slice(3),
  ],
};

const SAMPLE_GO = {
  ...SAMPLE_GO_WITH_WARNINGS,
  overall_verdict: "GO",
  summary: {checks_total: 10, ok: 10, warn: 0, fail: 0},
  checks: SAMPLE_GO_WITH_WARNINGS.checks.map((c) => ({...c, status: "ok"})),
  recommendations: [],
};


beforeEach(() => {
  getMock.mockReset();
});


describe("HealthCheckCard · I3", () => {
  it("renders the trigger button on mount", () => {
    render(<HealthCheckCard />);
    expect(screen.getByTestId("admin-health-check-card")).toBeInTheDocument();
    expect(screen.getByTestId("admin-health-check-btn")).toBeInTheDocument();
    // Modal not open until clicked.
    expect(screen.queryByTestId("admin-health-check-modal")).not.toBeInTheDocument();
  });

  it("clicking the button fires GET /admin/health-check/comprehensive and opens the modal", async () => {
    getMock.mockResolvedValue(SAMPLE_GO_WITH_WARNINGS);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(getMock).toHaveBeenCalledWith(
      "/admin/health-check/comprehensive",
    ));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-modal")).toBeInTheDocument());
  });

  it("renders the yellow GO_WITH_WARNINGS banner when verdict is GO_WITH_WARNINGS", async () => {
    getMock.mockResolvedValue(SAMPLE_GO_WITH_WARNINGS);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-verdict-go_with_warnings")).toBeInTheDocument());
    expect(screen.getByTestId("admin-health-check-verdict-label")
    ).toHaveTextContent(/GO WITH WARNINGS/i);
  });

  it("renders the green GO banner when verdict is GO", async () => {
    getMock.mockResolvedValue(SAMPLE_GO);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-verdict-go")).toBeInTheDocument());
  });

  it("renders the red NO_GO banner when verdict is NO_GO", async () => {
    getMock.mockResolvedValue(SAMPLE_NO_GO);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-verdict-no_go")).toBeInTheDocument());
  });

  it("renders one row per check with status pill + duration", async () => {
    getMock.mockResolvedValue(SAMPLE_GO_WITH_WARNINGS);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-rows")).toBeInTheDocument());
    // All 10 rows are present.
    for (const name of [
      "boot_state", "mongo_ping", "required_migrations",
      "optional_migrations", "hotpath_smoke", "comms_gate",
      "rc_sms_from_number", "scheduler", "env_sanity", "feature_gates",
    ]) {
      expect(screen.getByTestId(`admin-health-check-row-${name}`)
      ).toBeInTheDocument();
    }
    // Status pill for the failing check reads "warn" (for optional_migrations).
    expect(screen.getByTestId("admin-health-check-status-optional_migrations")
    ).toHaveTextContent(/warn/i);
  });

  it("renders the recommendations list", async () => {
    getMock.mockResolvedValue(SAMPLE_GO_WITH_WARNINGS);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-recommendations")).toBeInTheDocument());
    expect(screen.getByTestId("admin-health-check-recommendation-0")
    ).toHaveTextContent(/perf_customers_v2/);
    expect(screen.getByTestId("admin-health-check-recommendation-1")
    ).toHaveTextContent(/STRIPE_SECRET_KEY/);
  });

  it("hides the recommendations block when the list is empty", async () => {
    getMock.mockResolvedValue(SAMPLE_GO);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-verdict-go")).toBeInTheDocument());
    expect(screen.queryByTestId("admin-health-check-recommendations")
    ).not.toBeInTheDocument();
  });

  it("Copy JSON button writes the payload to the clipboard", async () => {
    getMock.mockResolvedValue(SAMPLE_GO_WITH_WARNINGS);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-copy-json")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("admin-health-check-copy-json"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const wrote = writeText.mock.calls[0][0];
    // Payload is stringified with 2-space indent.
    expect(wrote).toMatch(/"overall_verdict":\s*"GO_WITH_WARNINGS"/);
    expect(wrote).toMatch(/"tenant_id":\s*"aquaterra"/);
  });

  it("Copy JSON is disabled until a payload is available", async () => {
    // Simulate a network failure — no payload lands, Copy button
    // should stay disabled.
    getMock.mockRejectedValue(new Error("boom"));
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-error")).toBeInTheDocument());
    const btn = screen.getByTestId("admin-health-check-copy-json");
    expect(btn).toBeDisabled();
  });

  it("summary counts reflect the payload", async () => {
    getMock.mockResolvedValue(SAMPLE_GO_WITH_WARNINGS);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-summary-ok")).toHaveTextContent(/8 ok/));
    expect(screen.getByTestId("admin-health-check-summary-warn")
    ).toHaveTextContent(/2 warn/);
    expect(screen.getByTestId("admin-health-check-summary-fail")
    ).toHaveTextContent(/0 fail/);
  });

  it("close button dismisses the modal", async () => {
    getMock.mockResolvedValue(SAMPLE_GO);
    render(<HealthCheckCard />);
    fireEvent.click(screen.getByTestId("admin-health-check-btn"));
    await waitFor(() => expect(screen.getByTestId(
      "admin-health-check-modal")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("admin-health-check-close"));
    await waitFor(() => expect(screen.queryByTestId(
      "admin-health-check-modal")).not.toBeInTheDocument());
  });
});
