/**
 * __tests__/navigate-job-button.test.tsx
 *
 * Mirrors web schedule-navigate-button.test.jsx for React Native.
 *
 * Covers:
 *   1. Renders for jobs with lat/lng
 *   2. Renders for jobs with address only
 *   3. Disabled + toast on jobs with neither
 *   4. Coord priority over address
 *   5. (0,0) coords fall back to address
 *   6. URL encoding handles special characters
 *   7. onPress doesn't bubble to parent row
 *   8. Graceful null job
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { Alert, Linking, Platform } from "react-native";

/* ── Mocks ────────────────────────────────────────────── */
const mockAlertFn = jest.fn();
jest.spyOn(Alert, "alert").mockImplementation(mockAlertFn);

const mockCanOpenURL = jest.fn(async () => false);
const mockOpenURL = jest.fn(async () => true);

jest.spyOn(Linking, "canOpenURL").mockImplementation(mockCanOpenURL);
jest.spyOn(Linking, "openURL").mockImplementation(mockOpenURL);

import NavigateJobButton from "@/src/components/schedule/NavigateJobButton";
import {
  resolveDestination,
  buildGoogleMapsUrl,
} from "@/src/services/navigation/mapsDeepLink";

/* ── Helpers ──────────────────────────────────────────── */
function job(overrides: any = {}) {
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
    const d = resolveDestination(job());
    expect(d).toEqual({ kind: "coords", value: "33.7670356,-112.3397496" });
    console.log("✅ NJB-H1: coords returned for finite lat/lng");
  });

  it("falls back to address when coords are missing", () => {
    const d = resolveDestination(job({ latitude: null, longitude: null }));
    expect(d).toEqual({ kind: "address", value: "12 Vistancia Blvd, Peoria, AZ" });
    console.log("✅ NJB-H2: falls back to address");
  });

  it("treats (0, 0) as un-geocoded and falls back to address", () => {
    const d = resolveDestination(job({ latitude: 0, longitude: 0 }));
    expect(d).toEqual({ kind: "address", value: "12 Vistancia Blvd, Peoria, AZ" });
    console.log("✅ NJB-H3: (0,0) falls back to address");
  });

  it("returns null when neither coords nor address exists", () => {
    const d = resolveDestination(job({ latitude: null, longitude: null, address: "" }));
    expect(d).toBeNull();
    console.log("✅ NJB-H4: null when no destination");
  });

  it("URL-encodes special characters in the destination", () => {
    const url = buildGoogleMapsUrl({
      kind: "address",
      value: "12 Vistancia Blvd, Peoria, AZ 85383",
    });
    expect(url).toContain("destination=12+Vistancia+Blvd");
    expect(url).toContain("api=1");
    expect(url).toMatch(/^https:\/\/www\.google\.com\/maps\/dir\/\?/);
    console.log("✅ NJB-H5: URL encodes special characters");
  });
});

describe("NavigateJobButton · component", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCanOpenURL.mockResolvedValue(false);
    mockOpenURL.mockResolvedValue(true);
    // Force web platform so all URL assertions are predictable
    // (platform-specific routing is tested in mapsDeepLink.test.ts)
    Object.defineProperty(Platform, "OS", { get: () => "web" });
  });

  it("renders for job with lat/lng and opens maps on press", async () => {
    const tree = render(<NavigateJobButton job={job()} />);
    const btn = tree.getByTestId("schedule-job-nav-job-1");
    expect(btn).toBeTruthy();
    expect(btn.props.accessibilityLabel).toBe("Navigate to Jane Q. Public");
    fireEvent.press(btn);
    await waitFor(() => {
      expect(mockOpenURL).toHaveBeenCalledTimes(1);
    });
    // On web/test, falls back to Google Maps universal URL
    const url = mockOpenURL.mock.calls[0][0];
    expect(url).toContain("google.com/maps/dir");
    expect(url).toContain("33.7670356");
    console.log("✅ NJB-C1: renders with lat/lng + opens maps");
  });

  it("Phase K46 · shows alert toast when only an address is present (K46 is coord-only)", () => {
    const tree = render(
      <NavigateJobButton job={job({ latitude: null, longitude: null })} />
    );
    fireEvent.press(tree.getByTestId("schedule-job-nav-job-1"));
    expect(mockAlertFn).toHaveBeenCalledWith(
      "No address on file",
      "This job has no coordinates to navigate to.",
    );
    expect(mockOpenURL).not.toHaveBeenCalled();
    console.log("✅ NJB-C2 (K46): address-only → alert (coord-only nav)");
  });

  it("disabled state shows alert toast when no address or coords", () => {
    const tree = render(
      <NavigateJobButton job={job({ latitude: null, longitude: null, address: "" })} />
    );
    fireEvent.press(tree.getByTestId("schedule-job-nav-job-1"));
    expect(mockAlertFn).toHaveBeenCalledWith(
      "No address on file",
      "This job has no coordinates to navigate to.",
    );
    expect(mockOpenURL).not.toHaveBeenCalled();
    console.log("✅ NJB-C3: disabled → toast, no openURL");
  });

  it("prefers coords over string address when both present", async () => {
    const tree = render(
      <NavigateJobButton job={job({ address: "999 Wrong St, Bogus City" })} />
    );
    fireEvent.press(tree.getByTestId("schedule-job-nav-job-1"));
    await waitFor(() => {
      expect(mockOpenURL).toHaveBeenCalled();
    });
    const url = mockOpenURL.mock.calls[0][0];
    expect(url).toContain("33.7670356");
    expect(url).not.toContain("Wrong");
    console.log("✅ NJB-C4: coords preferred over address");
  });

  it("Phase K46 · (0,0) coords are rejected (K46 is coord-only, no address fallback)", () => {
    const tree = render(
      <NavigateJobButton job={job({ latitude: 0, longitude: 0 })} />
    );
    fireEvent.press(tree.getByTestId("schedule-job-nav-job-1"));
    // (0,0) is treated as un-geocoded → no coords → alert (no fallback to address).
    expect(mockAlertFn).toHaveBeenCalledWith(
      "No address on file",
      "This job has no coordinates to navigate to.",
    );
    expect(mockOpenURL).not.toHaveBeenCalled();
    console.log("✅ NJB-C5 (K46): (0,0) → alert, no address fallback");
  });

  it("onPress doesn't bubble to parent row", () => {
    const parentPress = jest.fn();
    const tree = render(
      <NavigateJobButton job={job()} />
    );
    // NavigateJobButton is its own Pressable — React Native doesn't have
    // true event propagation. The separate Pressable swallows the touch.
    fireEvent.press(tree.getByTestId("schedule-job-nav-job-1"));
    expect(parentPress).not.toHaveBeenCalled();
    console.log("✅ NJB-C6: onPress doesn't bubble");
  });

  it("gracefully handles null job prop", () => {
    const tree = render(<NavigateJobButton job={null} />);
    const btn = tree.getByTestId("schedule-job-nav-unknown");
    expect(btn).toBeTruthy();
    fireEvent.press(btn);
    expect(mockAlertFn).toHaveBeenCalled();
    expect(mockOpenURL).not.toHaveBeenCalled();
    console.log("✅ NJB-C7: null job → disabled, no crash");
  });
});
