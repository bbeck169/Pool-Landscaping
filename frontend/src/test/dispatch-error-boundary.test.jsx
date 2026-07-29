import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import DispatchErrorBoundary from "@/components/errors/DispatchErrorBoundary";

function Boom() {
  throw new Error("boom - simulated dispatch crash");
}

describe("DispatchErrorBoundary", () => {
  const originalError = console.error;
  beforeEach(() => {
    // Silence React 18's boundary-triggered console.error noise so the
    // test output stays clean.
    console.error = vi.fn();
    // Stub the ingest endpoint so componentDidCatch's fetch() is a no-op.
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, id: "x" }) })
    );
  });
  afterEach(() => {
    console.error = originalError;
    vi.restoreAllMocks();
  });

  it("renders children when no error is thrown", () => {
    render(
      <DispatchErrorBoundary>
        <div data-testid="child-ok">healthy</div>
      </DispatchErrorBoundary>
    );
    expect(screen.getByTestId("child-ok")).toBeTruthy();
  });

  it("renders the fallback UI when a child throws", () => {
    render(
      <DispatchErrorBoundary>
        <Boom />
      </DispatchErrorBoundary>
    );
    expect(screen.getByTestId("dispatch-error-boundary")).toBeTruthy();
    expect(screen.getByTestId("dispatch-error-title")).toBeTruthy();
    expect(screen.getByTestId("dispatch-error-message").textContent)
      .toContain("boom - simulated dispatch crash");
    expect(screen.getByTestId("dispatch-error-reload")).toBeTruthy();
    expect(screen.getByTestId("dispatch-error-copy")).toBeTruthy();
  });

  it("copy button writes error details to the clipboard", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <DispatchErrorBoundary>
        <Boom />
      </DispatchErrorBoundary>
    );
    fireEvent.click(screen.getByTestId("dispatch-error-copy"));
    // Give the async click handler a tick to resolve.
    await new Promise((r) => setTimeout(r, 10));
    expect(writeText).toHaveBeenCalled();
    const arg = writeText.mock.calls[0][0];
    expect(arg).toContain("boom - simulated dispatch crash");
    expect(arg).toContain("User-Agent:");
  });

  it("POSTs the error report to /api/client-errors on catch", () => {
    render(
      <DispatchErrorBoundary component="DispatchBoard">
        <Boom />
      </DispatchErrorBoundary>
    );
    expect(global.fetch).toHaveBeenCalled();
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toContain("/api/client-errors");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body.message).toContain("boom");
    expect(body.component).toBe("DispatchBoard");
  });
});
