// Queue Item 3 · Feb-2026 — source-inspection vitest for the
// Customer detail Tags section (web only). Locks in that:
//   • A labeled `CustomerTagsCard` component exists and is imported
//     by the customer detail page.
//   • The card is mounted inside the Overview tab (near
//     CustomerContactsPanel), not tucked away in an unrelated tab.
//   • The card re-uses the existing `CustomerTagPicker` (chip render
//     + combobox with "Create new: <query>" all preserved) — no
//     duplicate-picker regression.
//   • Empty-state copy is present so users know how to add the
//     first tag.
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const CARD_PATH = resolve(__dirname, "../components/customers/CustomerTagsCard.jsx");
const PAGE_PATH = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");

describe("Queue Item 3 · Customer detail Tags section", () => {
  it("CustomerTagsCard component file exists", () => {
    expect(existsSync(CARD_PATH)).toBe(true);
  });

  const cardSrc = readFileSync(CARD_PATH, "utf8");

  it("card imports and re-uses the existing CustomerTagPicker", () => {
    expect(cardSrc).toContain('from "@/components/customers/CustomerTagPicker"');
    expect(cardSrc).toContain("<CustomerTagPicker");
  });

  it("card exposes the section testIDs required by downstream tests", () => {
    expect(cardSrc).toContain('data-testid="customer-tags-section"');
    expect(cardSrc).toContain('data-testid="customer-tags-section-title"');
    expect(cardSrc).toContain('data-testid="customer-tags-section-count"');
    expect(cardSrc).toContain('data-testid="customer-tags-section-empty"');
  });

  it("card renders an empty-state hint pointing users at the picker", () => {
    // Should mention "No tags yet" so users understand the state.
    expect(cardSrc).toContain("No tags yet");
  });

  const pageSrc = readFileSync(PAGE_PATH, "utf8");

  it("CustomerDetail imports the new card", () => {
    expect(pageSrc).toContain(
      'import CustomerTagsCard from "@/components/customers/CustomerTagsCard"',
    );
  });

  it("CustomerDetail mounts the card inside the Overview tab layout", () => {
    // The Overview tab is gated by `tab === "overview"`. The new
    // card must live inside that branch — not lost inside jobs /
    // invoices / etc.
    const overviewIdx = pageSrc.indexOf('tab === "overview"');
    expect(overviewIdx).toBeGreaterThan(-1);
    // Next tab branch begins with the pattern `tab === "jobs"`.
    const jobsIdx = pageSrc.indexOf('tab === "jobs"');
    expect(jobsIdx).toBeGreaterThan(overviewIdx);
    const overviewBlock = pageSrc.slice(overviewIdx, jobsIdx);
    expect(overviewBlock).toContain("<CustomerTagsCard");
  });

  it("wires onChange back into the customer state so tags update in-place", () => {
    // Same optimistic-update pattern the header picker uses.
    expect(pageSrc).toMatch(/<CustomerTagsCard[\s\S]*?onChange=\{\(nextTags\) =>/);
  });
});
