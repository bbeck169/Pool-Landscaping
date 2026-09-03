/**
 * K37 · PortalErrorBoundary tests.
 *
 * Mirrors the pattern from `dispatch-error-boundary.test.jsx`.
 *
 * Covers:
 *   1. Happy path — renders children.
 *   2. Throw path — fallback UI shows with Reload + Copy buttons + error message.
 *   3. Copy button writes to the clipboard.
 *   4. `componentDidCatch` POSTs to `/api/client-errors` with the
 *      contract-required fields including `label`, `platform: "web"`,
 *      `component: "Portal"`, `route`, and `extra.componentStack`.
 *   5. `resetKey` change resets the boundary state so a route change
 *      doesn't leave the user stuck on a stale error screen.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PortalErrorBoundary from "@/components/errors/PortalErrorBoundary";

function Boom({ msg = "boom — simulated portal crash" }) {
  throw new Error(msg);
}

describe("PortalErrorBoundary", () => {
  const originalError = console.error;
  let fetchMock;

  beforeEach(() => {
    // Silence React 18's boundary-triggered console.error noise so the
    // test output stays clean.
    console.error = vi.fn();
    fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ok: true, id: "err_test" }),
      }),
    );
    global.fetch = fetchMock;
    // Give the clipboard a happy default.
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn(() => Promise.resolve()) },
    });
  });
  afterEach(() => {
    console.error = originalError;
    vi.restoreAllMocks();
  });

  it("renders children in the happy path", () => {
    render(
      <PortalErrorBoundary label="app-root">
        <div data-testid="child-ok">healthy portal</div>
      </PortalErrorBoundary>,
    );
    expect(screen.getByTestId("child-ok")).toBeTruthy();
    expect(screen.queryByTestId("portal-error-boundary")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the fallback UI with Reload + Copy when a child throws", () => {
    render(
      <PortalErrorBoundary label="app-root">
        <Boom />
      </PortalErrorBoundary>,
    );
    const boundary = screen.getByTestId("portal-error-boundary");
    expect(boundary).toBeTruthy();
    expect(boundary.getAttribute("data-boundary-label")).toBe("app-root");
    expect(screen.getByTestId("portal-error-title").textContent).toContain(
      "Something went wrong loading this page.",
    );
    expect(screen.getByTestId("portal-error-message").textContent).toContain(
      "boom — simulated portal crash",
    );
    expect(screen.getByTestId("portal-error-reload")).toBeTruthy();
    expect(screen.getByTestId("portal-error-copy")).toBeTruthy();
    expect(screen.getByTestId("portal-error-id").textContent).toContain(
      "Error ID:",
    );
  });

  it("Copy button writes error details to the clipboard and shows 'Copied' state", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <PortalErrorBoundary label="app-root">
        <Boom />
      </PortalErrorBoundary>,
    );
    const copyBtn = screen.getByTestId("portal-error-copy");
    expect(copyBtn.textContent).toContain("Copy details");
    fireEvent.click(copyBtn);
    // Give the async click handler a tick to resolve.
    await new Promise((r) => setTimeout(r, 5));
    expect(writeText).toHaveBeenCalledTimes(1);
    const payload = writeText.mock.calls[0][0];
    expect(payload).toContain("boom — simulated portal crash");
    expect(payload).toContain("Message:");
    expect(payload).toContain("Stack:");
    expect(payload).toContain("Error ID:");
  });

  it("POSTs to /api/client-errors with label, platform, component, route, and componentStack", async () => {
    render(
      <PortalErrorBoundary label="portal-shell">
        <Boom msg="fetch-shape-test" />
      </PortalErrorBoundary>,
    );
    // Give the fire-and-forget fetch a tick.
    await new Promise((r) => setTimeout(r, 5));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/client-errors");
    expect(opts.method).toBe("POST");
    // `keepalive: true` so the browser can flush during a tab unload.
    expect(opts.keepalive).toBe(true);
    expect(opts.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(opts.body);
    expect(body.message).toBe("fetch-shape-test");
    expect(body.stack).toBeTruthy();
    expect(body.component).toBe("Portal");
    expect(body.platform).toBe("web");
    expect(body.route).toBeDefined();
    expect(body.user_agent).toBeDefined();
    expect(body.extra).toBeTruthy();
    expect(body.extra.label).toBe("portal-shell");
    expect(body.extra.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    // componentStack lives in extra, matching the DispatchErrorBoundary contract.
    expect(body.extra.componentStack).toBeDefined();
  });

  it("resetKey change clears the error state (route-nav recovery)", () => {
    // Use a Harness component so we can flip resetKey after the throw.
    function Harness({ pathname, shouldThrow }) {
      return (
        <PortalErrorBoundary label="portal-shell" resetKey={pathname}>
          {shouldThrow ? <Boom /> : <div data-testid="ok-again">navigated ok</div>}
        </PortalErrorBoundary>
      );
    }
    const { rerender } = render(
      <Harness pathname="/portal/invoices/123" shouldThrow={true} />,
    );
    expect(screen.getByTestId("portal-error-boundary")).toBeTruthy();
    // Simulate route change + healthy child.
    rerender(<Harness pathname="/portal/home" shouldThrow={false} />);
    expect(screen.queryByTestId("portal-error-boundary")).toBeNull();
    expect(screen.getByTestId("ok-again")).toBeTruthy();
  });

  it("telemetry failure is swallowed — never rethrows past the boundary", async () => {
    global.fetch = vi.fn(() => Promise.reject(new Error("ingest down")));
    // If the fetch rejection escaped, this render would throw synchronously.
    expect(() =>
      render(
        <PortalErrorBoundary label="app-root">
          <Boom />
        </PortalErrorBoundary>,
      ),
    ).not.toThrow();
    // Still shows the fallback.
    expect(screen.getByTestId("portal-error-boundary")).toBeTruthy();
    // Give the microtask queue a beat so the rejected promise is settled.
    await new Promise((r) => setTimeout(r, 5));
    // Reporting label stays "Reporting…" because the POST rejected;
    // still non-empty, still non-throwing.
    expect(screen.getByTestId("portal-error-report-status")).toBeTruthy();
  });
});
