/**
 * Phase P23 · mobile-p23-calendar-istech-and-notes.test.tsx
 *
 * 1. Source-level: CalendarView receives isTech prop (no runtime crash).
 * 2. LandscapingChecklistForm renders internalNotes + customerNotes.
 * 3. checklist.tsx passes report.internal_notes / customer_notes.
 */

import * as fs from "fs";
import * as path from "path";
import React from "react";
import { render } from "@testing-library/react-native";

const ROOT = path.resolve(__dirname, "..");
function readSrc(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf-8");
}

/* ── Item 1: CalendarView isTech fix (source-level) ────────────── */
describe("CalendarView isTech prop (P23 Item 1)", () => {
  const src = readSrc("app/(app)/schedule/calendar.tsx");

  it("CalendarView call site passes isTech={isTech}", () => {
    // The JSX call to <CalendarView ... isTech={isTech} />
    expect(src).toMatch(/CalendarView[\s\S]*?isTech=\{isTech\}/);
  });

  it("CalendarView function destructures isTech", () => {
    // function CalendarView({ ..., isTech, ... })
    expect(src).toMatch(/function\s+CalendarView\(\{[\s\S]*?isTech[\s\S]*?\}\s*:\s*any\)/);
  });

  it("CalendarView body uses isTech (GpsConsentModal gate)", () => {
    // {isTech ? <GpsConsentModal /> : null}
    expect(src).toMatch(/isTech\s*\?\s*<GpsConsentModal/);
  });
});

/* ── Mocks for LandscapingChecklistForm ────────────────────────── */
jest.mock("@/src/components/ui/AppTextInput", () => {
  const R = require("react");
  const RN = require("react-native");
  return {
    __esModule: true,
    default: R.forwardRef((props: any, ref: any) =>
      R.createElement(RN.TextInput, {
        ...props,
        ref,
        testID: props.testID,
        value: props.value,
        placeholder: props.placeholder,
      }),
    ),
  };
});

import LandscapingChecklistForm from "@/src/components/checklist/LandscapingChecklistForm";

/* ── Item 2a: LandscapingChecklistForm renders notes ───────────── */
describe("LandscapingChecklistForm notes props (P23 Item 2)", () => {
  it("renders internalNotes and customerNotes in the text inputs", () => {
    const { getByTestId } = render(
      <LandscapingChecklistForm
        locked={false}
        checklistItems={[]}
        notes=""
        internalNotes="hello"
        customerNotes="world"
        onChange={jest.fn()}
      />
    );
    const internal = getByTestId("landscaping-internal-notes");
    const customer = getByTestId("landscaping-customer-notes");
    expect(internal.props.value).toBe("hello");
    expect(customer.props.value).toBe("world");
  });

  it("falls back to notes prop when internalNotes is undefined", () => {
    const { getByTestId } = render(
      <LandscapingChecklistForm
        locked={false}
        checklistItems={[]}
        notes="legacy note"
        onChange={jest.fn()}
      />
    );
    const internal = getByTestId("landscaping-internal-notes");
    expect(internal.props.value).toBe("legacy note");
  });
});

/* ── Item 2b: checklist.tsx passes report notes (source-level) ─── */
describe("checklist.tsx LandscapingChecklistForm call site (P23 Item 2b)", () => {
  const src = readSrc("app/job/[id]/checklist.tsx");

  it("passes internalNotes from report.internal_notes", () => {
    expect(src).toMatch(/internalNotes=\{report\.internal_notes\s*\|\|\s*""\}/);
  });

  it("passes customerNotes from report.customer_notes", () => {
    expect(src).toMatch(/customerNotes=\{report\.customer_notes\s*\|\|\s*""\}/);
  });
});
