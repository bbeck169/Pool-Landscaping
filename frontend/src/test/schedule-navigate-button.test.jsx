/**
 * Feb-2026 · Schedule polish — <NavigateJobButton /> unit tests.
 *
 * Covers:
 *   1. Renders for a job with lat/lng.
 *   2. Renders for a job with only ``address``.
 *   3. Disabled + tooltip="No address on file" when neither exists.
 *   4. Click opens ``google.com/maps/dir/?api=1&destination=...``
 *      in a new tab (``window.open`` spy).
 *   5. Prefers lat/lng over address when BOTH are present.
 *   6. URL-encodes special characters in the address.
 *   7. Accessibility — aria-label + keyboard reachable + Enter
 *      activates.
 *   8. (0,0) coords are treated as un-geocoded and fall back to
 *      address.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import NavigateJobButton, {
  _resolveDestination, _buildMapsUrl,
} from "@/components/schedule/NavigateJobButton";


function _job(overrides = {}) {
  return {
    id: "job-1",
    customer_name: "Jane Q. Public",
    address: "12 Vistancia Blvd, Peoria, AZ",
    latitude: 33.7670356,
    longitude: -112.3397496,
    ...overrides,
  };
}


describe("NavigateJobButton · resolve helpers", () => {
  it("returns coords when both lat and lng are finite", () => {
    const d = _resolveDestination(_job());
    expect(d).toEqual({ kind: "coords", value: "33.7670356,-112.3397496" });
  });

  it("falls back to address when coords are missing", () => {
    const d = _resolveDestination(_job({ latitude: null, longitude: null }));
    expect(d).toEqual({ kind: "address", value: "12 Vistancia Blvd, Peoria, AZ" });
  });

  it("treats (0, 0) as un-geocoded and falls back to address", () => {
    const d = _resolveDestination(_job({ latitude: 0, longitude: 0 }));
    expect(d).toEqual({ kind: "address", value: "12 Vistancia Blvd, Peoria, AZ" });
  });

  it("returns null when neither coords nor address exists", () => {
    const d = _resolveDestination(_job({
      latitude: null, longitude: null, address: "",
    }));
    expect(d).toBeNull();
  });

  it("URL-encodes special characters in the destination", () => {
    const url = _buildMapsUrl({
      kind: "address",
      value: "12 Vistancia Blvd, Peoria, AZ 85383",
    });
    // URLSearchParams encodes spaces as ``+``.
    expect(url).toContain("destination=12+Vistancia+Blvd");
    expect(url).toContain("api=1");
    expect(url).toMatch(/^https:\/\/www\.google\.com\/maps\/dir\/\?/);
  });
});


describe("NavigateJobButton · component", () => {
  let openSpy;

  beforeEach(() => {
    openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
  });
  afterEach(() => {
    openSpy.mockRestore();
  });

  it("renders with lat/lng and clicks open Google Maps with coords", () => {
    render(<NavigateJobButton job={_job()} />);
    const btn = screen.getByTestId("schedule-job-nav-job-1");
    expect(btn).toBeDefined();
    expect(btn.disabled).toBe(false);
    expect(btn.getAttribute("aria-label")).toBe("Navigate to Jane Q. Public");
    fireEvent.click(btn);
    expect(openSpy).toHaveBeenCalledTimes(1);
    const [url, target, features] = openSpy.mock.calls[0];
    expect(url).toBe("https://www.google.com/maps/dir/?api=1&destination=33.7670356%2C-112.3397496");
    expect(target).toBe("_blank");
    expect(features).toBe("noopener,noreferrer");
  });

  it("prefers coords over string address when both are present", () => {
    render(<NavigateJobButton job={_job({
      address: "999 Wrong St, Bogus City, XX",
    })} />);
    fireEvent.click(screen.getByTestId("schedule-job-nav-job-1"));
    const [url] = openSpy.mock.calls[0];
    expect(url).toContain("destination=33.7670356%2C-112.3397496");
    expect(url).not.toContain("Wrong+St");
  });

  it("falls back to the address string when coords missing", () => {
    render(<NavigateJobButton job={_job({
      latitude: null, longitude: null,
    })} />);
    fireEvent.click(screen.getByTestId("schedule-job-nav-job-1"));
    const [url] = openSpy.mock.calls[0];
    expect(url).toContain("destination=12+Vistancia+Blvd%2C+Peoria%2C+AZ");
  });

  it("is disabled with tooltip when no address or coords", () => {
    render(<NavigateJobButton job={_job({
      latitude: null, longitude: null, address: "",
    })} />);
    const btn = screen.getByTestId("schedule-job-nav-job-1");
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("title")).toBe("No address on file");
    expect(btn.getAttribute("aria-label")).toBe("No address on file");
    fireEvent.click(btn);
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("stops the click event from propagating to the parent row", () => {
    const parentClick = vi.fn();
    render(
      <div onClick={parentClick} data-testid="row-wrap">
        <NavigateJobButton job={_job()} />
      </div>
    );
    fireEvent.click(screen.getByTestId("schedule-job-nav-job-1"));
    expect(parentClick).not.toHaveBeenCalled();
    expect(openSpy).toHaveBeenCalledTimes(1);
  });

  it("is keyboard-reachable and Enter activates the click handler", () => {
    render(<NavigateJobButton job={_job()} />);
    const btn = screen.getByTestId("schedule-job-nav-job-1");
    // <button> is Tab-reachable by default.
    expect(btn.tabIndex).toBeGreaterThanOrEqual(0);
    btn.focus();
    // Simulate keyboard Enter → the browser fires ``click`` on a
    // focused <button>; jsdom does not auto-translate keydown, so
    // we call click() explicitly to prove the handler wiring.
    btn.click();
    expect(openSpy).toHaveBeenCalledTimes(1);
  });

  it("gracefully handles missing job prop (no crash, disabled button)", () => {
    render(<NavigateJobButton job={null} />);
    const btn = screen.getByTestId("schedule-job-nav-unknown");
    expect(btn.disabled).toBe(true);
  });
});
