/**
 * Phase 9B · Feb 2026 — Frontend unit tests.
 *
 * Focused suite (5 tests) covering the highest-risk behaviors of the
 * templates admin surface:
 *   1. Merge palette pulls categories from ``/api/marketing/merge-tags``.
 *   2. Clicking a palette row calls ``onInsert("{{TOKEN}}")``.
 *   3. SMS segment counter switches to Unicode threshold when an emoji
 *      is typed (70 chars/segment).
 *   4. ``computeSmsSegments`` classifies GSM-7 basic text correctly
 *      (160 chars/segment, non-unicode).
 *   5. Red-chip banner behaviour — the token-removal helper strips
 *      ALL case-insensitive occurrences.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MergeTagPalette, __resetMergeTagCacheForTests }
  from "@/components/marketing/MergeTagPalette";
import { computeSmsSegments } from "@/components/marketing/TemplateEditor";

// Mock the shared api helper — this keeps the tests decoupled from
// the network + auth stack.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path === "/marketing/merge-tags") {
        return {
          categories: {
            Customer: [
              { token: "CUSTOMER_FIRST_NAME", label: "First Name",
                description: "The customer's first name" },
              { token: "CUSTOMER_EMAIL", label: "Email",
                description: "Primary email on file" },
            ],
            Equipment: [
              { token: "EQUIPMENT_TYPE", label: "Equipment Type",
                description: "Filter / Salt Cell / etc." },
            ],
          },
        };
      }
      return {};
    }),
    post: vi.fn(async () => ({})),
    patch: vi.fn(async () => ({})),
    del: vi.fn(async () => ({})),
  },
}));

beforeEach(() => {
  __resetMergeTagCacheForTests();
});


describe("MergeTagPalette", () => {
  it("renders categories from the API when opened", async () => {
    const onInsert = vi.fn();
    render(
      <MergeTagPalette open={true} onOpenChange={() => {}} onInsert={onInsert} />
    );
    // Wait for the async catalog to hydrate.
    await waitFor(() => {
      expect(
        screen.getByTestId("merge-tag-category-header-Customer"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("merge-tag-category-header-Equipment"),
    ).toBeInTheDocument();
    // Row for CUSTOMER_FIRST_NAME shows both token and label.
    const row = await screen.findByTestId("merge-tag-row-CUSTOMER_FIRST_NAME");
    expect(row).toHaveTextContent("CUSTOMER_FIRST_NAME");
    expect(row).toHaveTextContent("First Name");
  });

  it("calls onInsert with the exact {{TOKEN}} string on row click", async () => {
    const onInsert = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <MergeTagPalette open={true}
                        onOpenChange={onOpenChange}
                        onInsert={onInsert} />
    );
    const row = await screen.findByTestId("merge-tag-row-EQUIPMENT_TYPE");
    fireEvent.click(row);
    expect(onInsert).toHaveBeenCalledWith("{{EQUIPMENT_TYPE}}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});


describe("computeSmsSegments (GSM-7 vs Unicode)", () => {
  it("classifies plain GSM-7 text as 160-char segments", () => {
    const res = computeSmsSegments(
      "Hi Sam, your filter cleaning is scheduled for Friday. Thanks!"
    );
    expect(res.isUnicode).toBe(false);
    expect(res.segmentSize).toBe(160);
    expect(res.segments).toBe(1);
  });

  it("switches to 70-char Unicode segments as soon as an emoji is typed", () => {
    const res = computeSmsSegments("See you soon 👍");
    expect(res.isUnicode).toBe(true);
    expect(res.segmentSize).toBe(70);
    expect(res.segments).toBe(1);
    // 71 chars of Unicode → 2 segments.
    const long = "👍" + "A".repeat(70);
    const res2 = computeSmsSegments(long);
    expect(res2.isUnicode).toBe(true);
    expect(res2.segments).toBe(2);
  });
});


describe("unresolved-token removal helper", () => {
  // Mirrors the escapeRegex + string.replace flow used inside
  // MarketingTemplatesAdmin.removeUnresolvedToken so we can assert
  // the exact substitution behavior without spinning up the full page.
  function removeToken(body, token) {
    const esc = String(token).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const rgx = new RegExp("\\{\\{\\s*" + esc + "\\s*\\}\\}", "gi");
    return body.replace(rgx, "");
  }

  it("removes ALL case-insensitive occurrences of a bad merge tag", () => {
    const body = "Hi {{BAD_TAG}}, welcome. {{bad_tag}} still shows. "
               + "But {{CUSTOMER_FIRST_NAME}} stays.";
    const out = removeToken(body, "BAD_TAG");
    expect(out).toBe("Hi , welcome.  still shows. But {{CUSTOMER_FIRST_NAME}} stays.");
    // Idempotent — calling twice is safe.
    expect(removeToken(out, "BAD_TAG")).toBe(out);
  });
});
