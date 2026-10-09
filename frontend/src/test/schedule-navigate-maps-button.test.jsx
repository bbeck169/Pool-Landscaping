/**
 * Phase 3b · Feb-2026 — "Navigate" button on the schedule job card.
 *
 * Locks the shared ``NavigateMapsButton`` contract:
 *   1. Enabled, orange (#F97316), label "Navigate".
 *   2. Click → ``window.open`` with the Google Maps ``dir`` URL
 *      pointing at the resolved destination, opened in a new tab
 *      with ``_blank`` + ``noopener,noreferrer``.
 *   3. Address priority: ``job.service_address`` wins over the
 *      ``job.address`` fallback.
 *   4. ``window.open`` is NOT called when the button is disabled.
 *   5. Both addresses empty / null → disabled (opacity-50,
 *      cursor-not-allowed, aria-disabled="true", no click handler
 *      attached, tooltip "No address on file").
 *
 * The two schedule pages both render ``<NavigateMapsButton>`` as
 * the LAST sibling in their respective action rows — asserted by
 * a source-level grep so a regression (someone moves it before
 * On-my-way or re-forks the button into one of the pages) fails
 * loudly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";

import NavigateMapsButton, {
  _resolveAddress,
  _buildMapsUrl,
} from "@/components/schedule/NavigateMapsButton";


afterEach(() => cleanup());


describe("Phase 3b · NavigateMapsButton — enabled behavior", () => {
  let openSpy;

  beforeEach(() => {
    openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
  });
  afterEach(() => openSpy.mockRestore());

  it("renders an orange 'Navigate' button when the job has an address", () => {
    render(
      <NavigateMapsButton
        job={{ id: "j1", customer_name: "Alpha",
                address: "123 Main St, Peoria AZ" }}
      />,
    );
    const btn = screen.getByTestId("schedule-card-navigate-j1");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toContain("Navigate");
    // Orange-500 bg, white text, orange-600 border.  JSDOM
    // normalises ``#F97316`` → ``rgb(249, 115, 22)``.
    expect(btn.style.backgroundColor.replace(/\s/g, ""))
      .toMatch(/rgb\(249,115,22\)|#F97316/i);
    expect(btn.style.color.replace(/\s/g, ""))
      .toMatch(/rgb\(255,255,255\)|#FFFFFF/i);
    expect(btn.getAttribute("aria-disabled")).toBe("false");
    expect(btn.disabled).toBe(false);
    // Hover darkens — Tailwind utility must be present so the
    // CSS cascade kicks in on hover.
    expect(btn.className).toContain("hover:bg-orange-600");
  });

  it("click opens Google Maps dir URL in a new tab (window.open spy)", () => {
    render(
      <NavigateMapsButton
        job={{ id: "jx", customer_name: "Alpha",
                address: "123 Main St, Peoria AZ" }}
      />,
    );
    fireEvent.click(screen.getByTestId("schedule-card-navigate-jx"));
    expect(openSpy).toHaveBeenCalledTimes(1);
    const [url, target, features] = openSpy.mock.calls[0];
    expect(url).toMatch(/^https:\/\/www\.google\.com\/maps\/dir\/\?/);
    expect(url).toMatch(/api=1/);
    expect(url).toMatch(/destination=123\+Main\+St/);
    expect(target).toBe("_blank");
    expect(features).toBe("noopener,noreferrer");
  });

  it("prefers job.service_address over job.address", () => {
    render(
      <NavigateMapsButton
        job={{
          id: "jp",
          customer_name: "Alpha",
          address:         "999 Fallback Ave",
          service_address: "42 Override Blvd",
        }}
      />,
    );
    fireEvent.click(screen.getByTestId("schedule-card-navigate-jp"));
    const [url] = openSpy.mock.calls[0];
    expect(url).toMatch(/destination=42\+Override\+Blvd/);
    expect(url).not.toMatch(/999\+Fallback/);
  });

  it("falls back to job.address when service_address is empty / whitespace / null", () => {
    for (const svc of ["", "   ", null, undefined]) {
      cleanup();
      openSpy.mockClear();
      render(
        <NavigateMapsButton
          job={{
            id: "jf",
            customer_name: "Alpha",
            service_address: svc,
            address:         "77 Customer Rd",
          }}
        />,
      );
      fireEvent.click(screen.getByTestId("schedule-card-navigate-jf"));
      expect(openSpy).toHaveBeenCalledTimes(1);
      const [url] = openSpy.mock.calls[0];
      expect(url).toMatch(/destination=77\+Customer\+Rd/);
    }
  });

  it("URL encodes special characters correctly", () => {
    render(
      <NavigateMapsButton
        job={{ id: "je", customer_name: "Alpha",
                address: "1st & Main #42, Peoria AZ" }}
      />,
    );
    fireEvent.click(screen.getByTestId("schedule-card-navigate-je"));
    const [url] = openSpy.mock.calls[0];
    // ``&`` → ``%26``, ``#`` → ``%23``, space → ``+``.
    expect(url).toMatch(/destination=1st\+%26\+Main\+%2342/);
  });
});


describe("Phase 3b · NavigateMapsButton — disabled behavior", () => {
  let openSpy;

  beforeEach(() => {
    openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
  });
  afterEach(() => openSpy.mockRestore());

  it("is disabled when BOTH addresses are missing", () => {
    render(
      <NavigateMapsButton
        job={{ id: "jd", customer_name: "Alpha" }}
      />,
    );
    const btn = screen.getByTestId("schedule-card-navigate-jd");
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("aria-disabled")).toBe("true");
    expect(btn.title).toBe("No address on file");
    expect(btn.style.opacity).toBe("0.5");
    expect(btn.style.cursor).toBe("not-allowed");
  });

  it("is disabled when both addresses are empty / whitespace strings", () => {
    render(
      <NavigateMapsButton
        job={{ id: "jd2", customer_name: "A",
                service_address: "", address: "   " }}
      />,
    );
    const btn = screen.getByTestId("schedule-card-navigate-jd2");
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("aria-disabled")).toBe("true");
  });

  it("does NOT call window.open when clicked while disabled", () => {
    render(
      <NavigateMapsButton
        job={{ id: "jdc", customer_name: "A" }}
      />,
    );
    // The button is disabled; React will NOT fire onClick on a
    // ``disabled`` native button via click events.  Simulate a
    // click anyway and assert the spy stays untouched.
    fireEvent.click(screen.getByTestId("schedule-card-navigate-jdc"));
    expect(openSpy).not.toHaveBeenCalled();
  });
});


describe("Phase 3b · pure helpers", () => {
  it("_resolveAddress prioritises service_address, then address, then empty string", () => {
    expect(_resolveAddress({
      service_address: "A", address: "B",
    })).toBe("A");
    expect(_resolveAddress({ address: "B" })).toBe("B");
    expect(_resolveAddress({})).toBe("");
    expect(_resolveAddress(null)).toBe("");
    // Whitespace-only is treated as empty.
    expect(_resolveAddress({
      service_address: "   ", address: "B",
    })).toBe("B");
  });

  it("_buildMapsUrl returns null for empty input and the dir URL otherwise", () => {
    expect(_buildMapsUrl("")).toBeNull();
    expect(_buildMapsUrl(null)).toBeNull();
    expect(_buildMapsUrl("42 X St"))
      .toBe("https://www.google.com/maps/dir/?api=1&destination=42+X+St");
  });
});


describe("Phase 3b · schedule pages render Navigate as LAST sibling", () => {
  it("TodaySchedule.jsx renders <NavigateMapsButton> AFTER Open Report", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/schedule/TodaySchedule.jsx"),
      "utf8",
    );
    const openReportIdx = src.indexOf("schedule-card-open-report-");
    const navigateIdx   = src.indexOf("<NavigateMapsButton");
    expect(openReportIdx).toBeGreaterThan(-1);
    expect(navigateIdx).toBeGreaterThan(-1);
    expect(navigateIdx).toBeGreaterThan(openReportIdx);
  });

  it("CalendarSchedule.jsx renders <NavigateMapsButton> AFTER Could not service", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
      "utf8",
    );
    const cnsIdx      = src.indexOf("could-not-service-btn-");
    const navigateIdx = src.indexOf("<NavigateMapsButton");
    expect(cnsIdx).toBeGreaterThan(-1);
    expect(navigateIdx).toBeGreaterThan(-1);
    expect(navigateIdx).toBeGreaterThan(cnsIdx);
  });
});
