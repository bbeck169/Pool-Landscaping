/**
 * Feb-2026 · Schedule polish — Job Notes visibility bump (Jest).
 *
 * Covers 3 behavioural assertions of the mobile <JobNotesCallout>:
 *   1. Notes render with the accented amber container.
 *   2. Empty notes ⇒ nothing rendered (no placeholder chip).
 *   3. Long notes ⇒ 2-line clamp + Show more toggle expands inline.
 */
import React from "react";
import { render, fireEvent, cleanup } from "@testing-library/react-native";

import JobNotesCallout from "@/src/components/schedule/JobNotesCallout";

const JOB_ID = "j-42";

describe("JobNotesCallout · mobile", () => {
  afterEach(() => cleanup());

  it("renders the accented amber container when a note is present", () => {
    const { getByTestId } = render(
      <JobNotesCallout jobId={JOB_ID} note="Skimmer basket has crack" />,
    );
    const chip = getByTestId(`job-notes-callout-${JOB_ID}`);
    // React Native flattens style into a plain object per rendered element;
    // grab it from the props to assert the amber palette applied.
    const style = Array.isArray(chip.props.style)
      ? Object.assign({}, ...chip.props.style.filter(Boolean))
      : chip.props.style || {};
    expect(style.backgroundColor).toBe("#FEF3C7");
    expect(style.borderLeftColor).toBe("#F59E0B");
    expect(style.borderLeftWidth).toBe(3);
    // Note text renders exactly.
    expect(getByTestId(`job-${JOB_ID}-notes`).props.children[0])
      .toBe("Skimmer basket has crack");
  });

  it("returns null when there is no job note AND no customer note", () => {
    const { queryByTestId, toJSON } = render(<JobNotesCallout jobId={JOB_ID} />);
    expect(queryByTestId(`job-notes-callout-${JOB_ID}`)).toBeNull();
    expect(toJSON()).toBeNull();
  });

  it("long notes → 2-line clamp + Show more toggle expands inline", () => {
    const longNote = "N".repeat(180) + " tail";
    const { getByTestId } = render(
      <JobNotesCallout jobId={JOB_ID} note={longNote} />,
    );
    const body = getByTestId(`job-${JOB_ID}-notes`);
    // Initially clamped to 2 lines.
    expect(body.props.numberOfLines).toBe(2);
    const toggle = getByTestId(`job-notes-toggle-${JOB_ID}`);
    expect(toggle.props.accessibilityLabel).toBe("Show more");
    // Tap the toggle — clamp lifts, label flips to "Show less".
    fireEvent.press(toggle);
    expect(body.props.numberOfLines).toBeUndefined();
    expect(getByTestId(`job-notes-toggle-${JOB_ID}`).props.accessibilityLabel)
      .toBe("Show less");
  });
});
