/**
 * Phase R0.1 · Feb-2026 — downloadCsv helper tests.
 *
 * Covers:
 *   1. Escapes cells containing commas, quotes, and newlines.
 *   2. Prepends BOM + joins rows with CRLF for Excel compatibility.
 *   3. Handles null / undefined cells as empty strings.
 *   4. Triggers an <a download="…"> click with the passed filename.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { downloadCsv } from "../components/reports/downloadCsv";

describe("R0.1 · downloadCsv", () => {
  let capturedBlob = null;
  let capturedText = null;

  beforeEach(() => {
    capturedBlob = null;
    capturedText = null;
    const RealBlob = global.Blob;
    // Capture the Blob contents synchronously so we can assert on them.
    global.Blob = class MockBlob {
      constructor(parts, opts) {
        capturedText = parts.join("");
        capturedBlob = new RealBlob(parts, opts);
      }
    };
    global.URL.createObjectURL = vi.fn(() => "blob:mock");
    global.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("escapes commas and quotes in cells", () => {
    downloadCsv("f.csv", ["A", "B"], [["hello, world", 'she said "hi"']]);
    expect(capturedText.startsWith("\uFEFF")).toBe(true);
    // Header + one data row, joined by CRLF
    const lines = capturedText.slice(1).split("\r\n");
    expect(lines[0]).toBe("A,B");
    expect(lines[1]).toBe('"hello, world","she said ""hi"""');
  });

  it("renders null/undefined as empty and preserves numbers", () => {
    downloadCsv("f.csv", ["X", "Y"], [[null, 42]]);
    const lines = capturedText.slice(1).split("\r\n");
    expect(lines[1]).toBe(",42");
  });

  it("quotes cells containing embedded newlines", () => {
    downloadCsv("f.csv", ["Note"], [["line1\nline2"]]);
    const lines = capturedText.slice(1).split("\r\n");
    // Header line + quoted multi-line cell (which itself contains \n)
    expect(lines[0]).toBe("Note");
    // The remaining part must start with an opening quote because the
    // embedded \n bleeds into the next split() token.
    expect(lines[1].startsWith('"line1')).toBe(true);
  });

  it("clicks a hidden anchor with the requested filename", () => {
    const clicks = [];
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      const el = origCreate(tag);
      if (tag === "a") {
        el.click = () => clicks.push(el.getAttribute("download"));
      }
      return el;
    });
    downloadCsv("revenue.csv", ["A"], [[1]]);
    expect(clicks).toEqual(["revenue.csv"]);
  });
});
