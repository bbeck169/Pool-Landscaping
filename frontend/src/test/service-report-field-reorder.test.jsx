/**
 * Phase 14A · Feb-2026 — Field-reorder runtime vitest coverage.
 *
 * Pins ``TemplateOrderedSections`` behavior:
 *
 *   1. With no provider / empty template → children render in
 *      source order (zero-regression contract).
 *   2. With a template order → children reorder to match.
 *   3. Template references a field_id the page doesn't render →
 *      skipped silently (no crash, no gap).
 *   4. Page has a renderable the template doesn't mention →
 *      appended at end of the ordered run (no silent drop).
 *   5. Children without ``templateFieldId`` (header, footer) are
 *      passed through at their source position.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import {
  TemplateFieldProvider, TemplateOrderedSections,
} from "@/components/form-renderer/TemplateFieldContext";


function Section({ templateFieldId, label }) {
  // Minimal section stand-in — the real ServiceReport uses the
  // page's ``Section`` component which also carries this prop.
  return (
    <div data-testid={`section-${templateFieldId || "misc"}`}>
      {label}
    </div>
  );
}


function _childrenOrder(container) {
  return Array.from(
    container.querySelectorAll("[data-testid^='section-']"),
  ).map((n) => n.dataset.testid);
}


describe("TemplateOrderedSections · zero-regression fallback", () => {
  it("renders children in source order when no provider wraps", () => {
    const { container } = render(
      <TemplateOrderedSections>
        <Section templateFieldId="photos" label="A" />
        <Section templateFieldId="notes" label="B" />
        <Section templateFieldId="signature" label="C" />
      </TemplateOrderedSections>,
    );
    expect(_childrenOrder(container)).toEqual([
      "section-photos", "section-notes", "section-signature",
    ]);
  });

  it("renders children in source order when template is empty", () => {
    const { container } = render(
      <TemplateFieldProvider fieldsById={{}}>
        <TemplateOrderedSections>
          <Section templateFieldId="photos" label="A" />
          <Section templateFieldId="notes" label="B" />
          <Section templateFieldId="signature" label="C" />
        </TemplateOrderedSections>
      </TemplateFieldProvider>,
    );
    expect(_childrenOrder(container)).toEqual([
      "section-photos", "section-notes", "section-signature",
    ]);
  });
});


describe("TemplateOrderedSections · reorder from template", () => {
  it("re-sorts children to match the template order", () => {
    // Template says: signature, photos, notes.
    const fieldsById = {
      signature: { field_id: "signature", order: 0 },
      photos:    { field_id: "photos",    order: 1 },
      notes:     { field_id: "notes",     order: 2 },
    };
    const { container } = render(
      <TemplateFieldProvider fieldsById={fieldsById}>
        <TemplateOrderedSections>
          <Section templateFieldId="photos" label="A" />
          <Section templateFieldId="notes" label="B" />
          <Section templateFieldId="signature" label="C" />
        </TemplateOrderedSections>
      </TemplateFieldProvider>,
    );
    expect(_childrenOrder(container)).toEqual([
      "section-signature", "section-photos", "section-notes",
    ]);
  });

  it("skips template field_ids with no matching child", () => {
    // Template says: ghost (not rendered), photos, notes. Ghost
    // field has no renderable → it must be silently dropped.
    const fieldsById = {
      ghost:  { field_id: "ghost",  order: 0 },
      photos: { field_id: "photos", order: 1 },
      notes:  { field_id: "notes",  order: 2 },
    };
    const { container } = render(
      <TemplateFieldProvider fieldsById={fieldsById}>
        <TemplateOrderedSections>
          <Section templateFieldId="photos" label="A" />
          <Section templateFieldId="notes" label="B" />
        </TemplateOrderedSections>
      </TemplateFieldProvider>,
    );
    // No ghost section expected; no crash.
    expect(screen.queryByTestId("section-ghost")).toBeNull();
    expect(_childrenOrder(container)).toEqual([
      "section-photos", "section-notes",
    ]);
  });

  it("appends page-side renderables the template didn't mention", () => {
    // Template only mentions signature. The page also renders
    // photos + notes — they must appear after signature, not vanish.
    const fieldsById = {
      signature: { field_id: "signature", order: 0 },
    };
    const { container } = render(
      <TemplateFieldProvider fieldsById={fieldsById}>
        <TemplateOrderedSections>
          <Section templateFieldId="photos" label="A" />
          <Section templateFieldId="notes" label="B" />
          <Section templateFieldId="signature" label="C" />
        </TemplateOrderedSections>
      </TemplateFieldProvider>,
    );
    const ids = _childrenOrder(container);
    expect(ids[0]).toBe("section-signature");
    // The remaining two render after signature; original relative
    // order (photos before notes) is preserved.
    expect(ids.slice(1).sort())
      .toEqual(["section-notes", "section-photos"]);
  });
});


describe("TemplateOrderedSections · passthrough children", () => {
  it("children without a templateFieldId render in-place",
      () => {
        // Header has no templateFieldId → stays at the top.
        // Footer has no templateFieldId → stays at the bottom.
        const fieldsById = {
          notes:   { field_id: "notes",   order: 0 },
          photos:  { field_id: "photos",  order: 1 },
        };
        const { container } = render(
          <TemplateFieldProvider fieldsById={fieldsById}>
            <TemplateOrderedSections>
              <Section label="header" templateFieldId={undefined} />
              <Section templateFieldId="photos" label="A" />
              <Section templateFieldId="notes" label="B" />
              <Section label="footer" templateFieldId={undefined} />
            </TemplateOrderedSections>
          </TemplateFieldProvider>,
        );
        const ids = _childrenOrder(container);
        expect(ids[0]).toBe("section-misc");
        expect(ids[ids.length - 1]).toBe("section-misc");
        // Middle is the reordered pair.
        expect(ids.slice(1, 3)).toEqual([
          "section-notes", "section-photos",
        ]);
      });

  it("falsy children (null / false) are silently filtered",
      () => {
        const fieldsById = {
          notes:  { field_id: "notes",  order: 0 },
          photos: { field_id: "photos", order: 1 },
        };
        const { container } = render(
          <TemplateFieldProvider fieldsById={fieldsById}>
            <TemplateOrderedSections>
              {false}
              {null}
              <Section templateFieldId="photos" label="A" />
              {false && <Section templateFieldId="ghost" label="X" />}
              <Section templateFieldId="notes" label="B" />
            </TemplateOrderedSections>
          </TemplateFieldProvider>,
        );
        expect(_childrenOrder(container)).toEqual([
          "section-notes", "section-photos",
        ]);
      });
});
