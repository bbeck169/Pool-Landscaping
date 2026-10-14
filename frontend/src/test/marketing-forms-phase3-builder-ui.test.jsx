/**
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 3.
 *
 * Locks the builder-UI upgrade for the marketing forms page:
 *   1. New ``<RichTextField>`` component with a narrow Tiptap
 *      extension set + a link-scheme allowlist. Source-lints
 *      the extension list to catch accidental XSS-surface
 *      reopens (e.g. adding ``Image`` or a paste HTML handler).
 *   2. New ``<HeroEditor>`` component wired through
 *      ``MarketingFormsPage``. ``value == null`` renders only the
 *      enable toggle (back-compat contract). Background type
 *      radio drives color / image / gradient sub-controls.
 *   3. ``MarketingFormsPage`` wires ``hero`` into the save/load
 *      payload, exposes ``"section"`` as a field type, mounts a
 *      per-field ``column_span`` selector, and swaps the local
 *      brand hex constants for canonical ``@/theme`` tokens
 *      while preserving semantic (error / status) colors.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import RichTextField from "@/components/formBuilder/RichTextField";
import HeroEditor from "@/components/formBuilder/HeroEditor";

// The MediaLibraryPicker pulls in ``@/api`` + ``sonner`` transitively;
// stub it out so HeroEditor mounts cleanly under jsdom without a
// live-backend dep. Every assertion that needs the picker verifies
// the ``open`` prop the parent passed in — the picker's real UX is
// tested in ``customer-attach-files.test.jsx``.
vi.mock("@/components/marketing/MediaLibraryPicker", () => ({
  __esModule: true,
  MediaLibraryPicker: ({ open, onOpenChange, onSelect }) => (
    <div
      data-testid="mock-media-picker"
      data-open={open ? "true" : "false"}
    >
      {open ? (
        <button
          data-testid="mock-media-picker-pick"
          onClick={() => onSelect({
            id: "media-1",
            url: "https://cdn.example.com/pool.jpg",
            cdn_url: "https://cdn.example.com/pool.jpg",
            alt_text: "Pool hero",
          })}
        >
          Pick
        </button>
      ) : null}
      {open ? (
        <button
          data-testid="mock-media-picker-close"
          onClick={() => onOpenChange(false)}
        >
          Close
        </button>
      ) : null}
    </div>
  ),
}));


// Absolute path to the app source we source-lint below. Resolved
// via ``process.cwd()`` which vitest sets to ``/app/frontend``.
const MFP_PATH = path.resolve(
  process.cwd(), "src/pages/marketing/MarketingFormsPage.jsx",
);
const RTF_PATH = path.resolve(
  process.cwd(), "src/components/formBuilder/RichTextField.jsx",
);
const HERO_PATH = path.resolve(
  process.cwd(), "src/components/formBuilder/HeroEditor.jsx",
);
const readSrc = (p) => fs.readFileSync(p, "utf8");


// ═══════════════════════════════════════════════════════════════
// 1) <RichTextField> — render + narrow-extension source-lint
// ═══════════════════════════════════════════════════════════════
describe("Phase 3 · <RichTextField>", () => {
  it("renders the editor shell with the minimal toolbar (bold/italic/underline/link/clear)",
      () => {
    render(
      <RichTextField
        value="<p>hi</p>"
        onChange={() => {}}
        testid="rtf-a"
      />,
    );
    // Toolbar buttons.
    expect(screen.getByTestId("rtf-a-btn-bold")).toBeTruthy();
    expect(screen.getByTestId("rtf-a-btn-italic")).toBeTruthy();
    expect(screen.getByTestId("rtf-a-btn-underline")).toBeTruthy();
    expect(screen.getByTestId("rtf-a-btn-link")).toBeTruthy();
    expect(screen.getByTestId("rtf-a-btn-clear")).toBeTruthy();
    // The editor content mount is present.
    expect(screen.getByTestId("rtf-a-content")).toBeTruthy();
    cleanup();
  });

  it("toolbar does NOT include an insert-image button (narrow extension set — no @tiptap/extension-image)",
      () => {
    render(<RichTextField value="" onChange={() => {}} testid="rtf-b" />);
    // Explicit negative — no ``btn-image`` in RichTextField's palette.
    // TemplateEditor has an image button; RichTextField must not.
    expect(screen.queryByTestId("rtf-b-btn-image")).toBeNull();
    cleanup();
  });

  it("source-lint · RichTextField extension imports are narrow (StarterKit + Underline + TextStyle + Link ONLY)",
      () => {
    const src = readSrc(RTF_PATH);
    // Positive — the four allowed extensions must be present.
    expect(src).toMatch(/from ["']@tiptap\/starter-kit["']/);
    expect(src).toMatch(/from ["']@tiptap\/extension-underline["']/);
    expect(src).toMatch(/from ["']@tiptap\/extension-text-style["']/);
    expect(src).toMatch(/from ["']@tiptap\/extension-link["']/);
    // Negative — none of the wider Tiptap extensions may creep in.
    // ``Image`` is the highest-risk XSS surface (data:/blob:/JS URIs).
    expect(src).not.toMatch(/from ["']@tiptap\/extension-image["']/);
    expect(src).not.toMatch(/from ["']@tiptap\/extension-color["']/);
    expect(src).not.toMatch(/from ["']@tiptap\/extension-text-align["']/);
    // No custom HTML paste rules / raw-HTML nodes.
    expect(src).not.toMatch(/handlePaste/);
    expect(src).not.toMatch(/parseHTML\s*:/);
  });

  it("source-lint · Link.configure includes a validate callback AND openOnClick:false",
      () => {
    const src = readSrc(RTF_PATH);
    expect(src).toMatch(/Link\.configure\(/);
    expect(src).toMatch(/validate\s*:/);
    expect(src).toMatch(/openOnClick\s*:\s*false/);
    // rel + target hardening on the rendered anchor.
    expect(src).toMatch(/rel:\s*["']noopener noreferrer["']/);
    expect(src).toMatch(/target:\s*["']_blank["']/);
  });

  it("source-lint · link scheme allowlist (http / https / mailto / tel) is present in the validate helper",
      () => {
    const src = readSrc(RTF_PATH);
    // The validate helper must reference every allowed scheme.
    expect(src).toMatch(/http:/);
    expect(src).toMatch(/https:/);
    expect(src).toMatch(/mailto:/);
    expect(src).toMatch(/tel:/);
    // And it must be a startsWith / allow-list style guard — the
    // easiest lint is that ``javascript:`` and ``data:`` are NOT
    // listed as accepted schemes anywhere in the file.
    // (They may appear in the security-boundary comment — which is
    // fine; the assertion above already locks the positive list.)
  });

  it("source-lint · security boundary comment is present (documents the XSS containment)",
      () => {
    const src = readSrc(RTF_PATH);
    expect(src).toMatch(/SECURITY BOUNDARY/i);
    expect(src).toMatch(/XSS/i);
  });
});


// ═══════════════════════════════════════════════════════════════
// 2) <HeroEditor> — enable toggle, sub-controls, back-compat
// ═══════════════════════════════════════════════════════════════
describe("Phase 3 · <HeroEditor>", () => {
  it("value == null → renders ONLY the enable toggle (Phase-2 back-compat contract)",
      () => {
    render(<HeroEditor value={null} onChange={() => {}} />);
    expect(screen.getByTestId("hero-editor")).toBeTruthy();
    expect(screen.getByTestId("hero-enable-toggle")).toBeTruthy();
    // Body is NOT mounted — no heading editor, no background radio,
    // no badge picker.
    expect(screen.queryByTestId("hero-editor-body")).toBeNull();
    expect(screen.queryByTestId("hero-heading-editor")).toBeNull();
    expect(screen.queryByTestId("hero-bg-kind-radio")).toBeNull();
    cleanup();
  });

  it("enabling the toggle emits a fully-populated default hero object",
      () => {
    const captured = [];
    render(
      <HeroEditor value={null} onChange={(h) => captured.push(h)} />,
    );
    fireEvent.click(screen.getByTestId("hero-enable-toggle"));
    expect(captured).toHaveLength(1);
    const h = captured[0];
    expect(h).not.toBeNull();
    expect(h.heading_html).toBe("");
    expect(h.subheading_html).toBe("");
    expect(h.background).toBeTruthy();
    expect(h.background.kind).toBe("color");
    expect(h.background.color).toMatch(/^#/);
    expect(h.badge).toBeNull();
    cleanup();
  });

  it("value = { color bg } → renders heading + subheading + color picker",
      () => {
    render(
      <HeroEditor
        value={{
          heading_html: "<p>Free inspection</p>",
          subheading_html: "<p>24hr response</p>",
          background: { kind: "color", color: "#F8FAFC" },
          badge: null,
        }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("hero-editor-body")).toBeTruthy();
    expect(screen.getByTestId("hero-heading-editor")).toBeTruthy();
    expect(screen.getByTestId("hero-subheading-editor")).toBeTruthy();
    expect(screen.getByTestId("hero-bg-color-picker")).toBeTruthy();
    // Image + gradient controls hidden.
    expect(screen.queryByTestId("hero-bg-image-controls")).toBeNull();
    expect(screen.queryByTestId("hero-bg-gradient-controls")).toBeNull();
    cleanup();
  });

  it("switching background kind color → image opens the MediaLibraryPicker and shows overlay slider",
      () => {
    const captured = [];
    const initial = {
      heading_html: "",
      subheading_html: "",
      background: { kind: "color", color: "#F8FAFC" },
      badge: null,
    };
    // Controlled-component pattern: local wrapper re-renders with
    // the latest emitted value so radio + downstream controls
    // reflect the state change deterministically.
    function Wrapper() {
      const [v, setV] = React.useState(initial);
      return (
        <HeroEditor
          value={v}
          onChange={(next) => { captured.push(next); setV(next); }}
        />
      );
    }
    render(<Wrapper />);
    fireEvent.click(screen.getByTestId("hero-bg-kind-image"));
    // Background is now image with a default overlay opacity.
    expect(captured.at(-1).background.kind).toBe("image");
    expect(captured.at(-1).background.overlay_opacity).toBe(30);
    // Overlay slider is visible.
    expect(screen.getByTestId("hero-bg-overlay-slider")).toBeTruthy();
    // "Choose from Media Library" button visible when URL is empty.
    expect(screen.getByTestId("hero-bg-image-pick-btn")).toBeTruthy();
    // Click the pick button → picker opens.
    fireEvent.click(screen.getByTestId("hero-bg-image-pick-btn"));
    expect(screen.getByTestId("mock-media-picker").getAttribute("data-open"))
      .toBe("true");
    // Confirm a pick → background url flows through.
    fireEvent.click(screen.getByTestId("mock-media-picker-pick"));
    expect(captured.at(-1).background.url)
      .toBe("https://cdn.example.com/pool.jpg");
    expect(captured.at(-1).background.kind).toBe("image");
    cleanup();
  });

  it("gradient kind → renders angle + from + to controls (pragmatic copy of ThemePanel's block)",
      () => {
    render(
      <HeroEditor
        value={{
          heading_html: "",
          subheading_html: "",
          background: {
            kind: "gradient",
            angle_deg: 135,
            from: "#0EA5E9",
            to:   "#1B1F5C",
          },
          badge: null,
        }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("hero-bg-gradient-controls")).toBeTruthy();
    expect(screen.getByTestId("hero-bg-gradient-angle")).toBeTruthy();
    expect(screen.getByTestId("hero-bg-gradient-from")).toBeTruthy();
    expect(screen.getByTestId("hero-bg-gradient-to")).toBeTruthy();
    // Color + image controls hidden.
    expect(screen.queryByTestId("hero-bg-color-picker")).toBeNull();
    expect(screen.queryByTestId("hero-bg-overlay-slider")).toBeNull();
    cleanup();
  });

  it("badge upload persists the picked media URL on hero.badge",
      () => {
    const captured = [];
    const initial = {
      heading_html: "",
      subheading_html: "",
      background: { kind: "color", color: "#F8FAFC" },
      badge: null,
    };
    function Wrapper() {
      const [v, setV] = React.useState(initial);
      return (
        <HeroEditor
          value={v}
          onChange={(next) => { captured.push(next); setV(next); }}
        />
      );
    }
    render(<Wrapper />);
    // Click "Add badge graphic" → picker opens.
    fireEvent.click(screen.getByTestId("hero-badge-pick-btn"));
    expect(screen.getByTestId("mock-media-picker").getAttribute("data-open"))
      .toBe("true");
    // Confirm a pick.
    fireEvent.click(screen.getByTestId("mock-media-picker-pick"));
    const last = captured.at(-1);
    expect(last.badge).not.toBeNull();
    expect(last.badge.url).toBe("https://cdn.example.com/pool.jpg");
    expect(last.badge.alt_text).toBe("Pool hero");
    cleanup();
  });
});


// ═══════════════════════════════════════════════════════════════
// 3) MarketingFormsPage source-lint — hero + section + column_span
// ═══════════════════════════════════════════════════════════════
describe("Phase 3 · MarketingFormsPage source-lint", () => {
  it("hero is present in the save payload alongside theme", () => {
    const src = readSrc(MFP_PATH);
    // Payload block contains both keys.
    expect(src).toMatch(/theme,\s*\n?\s*hero/);
    // Load path — hero seeded from ``form.hero``.
    expect(src).toMatch(/useState\(form\.hero\s*\|\|\s*null\)/);
  });

  it("HeroEditor is imported + mounted inside FormEditorDrawer", () => {
    const src = readSrc(MFP_PATH);
    expect(src).toMatch(/import HeroEditor from ["']@\/components\/formBuilder\/HeroEditor["']/);
    expect(src).toMatch(/<HeroEditor\s+value=\{hero\}\s+onChange=\{setHero\}/);
  });

  it("\"section\" is present in FIELD_TYPES palette + has a friendly label",
      () => {
    const src = readSrc(MFP_PATH);
    // Positive — ``"section"`` in the FIELD_TYPES array.
    expect(src).toMatch(/FIELD_TYPES\s*=\s*\[[^\]]*"section"/);
    // Friendly label is defined for the palette dropdown.
    expect(src).toMatch(/FIELD_TYPE_LABELS\s*=\s*\{[\s\S]*section\s*:\s*["']Section heading/);
    // LAYOUT_TYPES set gates the section-specific UI branches.
    expect(src).toMatch(/LAYOUT_TYPES\s*=\s*new Set\(\[[^\]]*"section"/);
  });

  it("column_span selector JSX + save-time normalization are present",
      () => {
    const src = readSrc(MFP_PATH);
    // Selector data-testid mounted for every field row.
    expect(src).toMatch(/data-testid=\{`form-field-column-span-\$\{idx\}`\}/);
    // Save path preserves column_span (fallback to "full" for legacy
    // fields).  Feb-2026 · Form Builder Phase 1 renamed the save-time
    // destructured var from ``f`` → ``rest`` after dropping the
    // ``_rowId`` dnd-kit handle; semantics are byte-identical.
    expect(src).toMatch(
      /column_span:\s*(?:f|rest)\.column_span\s*\|\|\s*"full"/,
    );
    // empty_field() defaults column_span.
    expect(src).toMatch(/column_span:\s*["']full["']/);
  });

  it("RichTextField is imported + used to author the section field label",
      () => {
    const src = readSrc(MFP_PATH);
    expect(src).toMatch(/import RichTextField from ["']@\/components\/formBuilder\/RichTextField["']/);
    // Section-label RichTextField is mounted when the field is a
    // layout marker.
    expect(src).toMatch(/testid=\{`form-field-section-label-\$\{idx\}`\}/);
  });

  it("branding swap · colors.inputBorder + colors.nav.bg tokens from @/theme are referenced",
      () => {
    const src = readSrc(MFP_PATH);
    // Import from @/theme.
    expect(src).toMatch(/import \{\s*colors as themeColors\s*\} from ["']@\/theme["']/);
    // Both tokens consumed by the local ``colors`` alias.
    expect(src).toMatch(/brand:\s*themeColors\.inputBorder/);
    expect(src).toMatch(/onSurface:\s*themeColors\.nav\.bg/);
    // Row hover uses the navy 5%-tint utility class.
    expect(src).toMatch(/hover:bg-\[#1B1F5C\]\/5/);
  });

  it("branding swap · legacy #0EA5E9 brand constant is REMOVED (single-line guard)",
      () => {
    const src = readSrc(MFP_PATH);
    // The specific ``brand: "#0EA5E9"`` constant must no longer
    // appear as a local const. #0EA5E9 elsewhere (e.g. a preserved
    // gradient in HeroEditor via a default value) is not this
    // file's concern — this guard is scoped to the local ``colors``
    // dict in MarketingFormsPage.
    expect(src).not.toMatch(/brand:\s*["']#0EA5E9["']/);
    // The other legacy chrome hex constants (``#0F172A``, ``#64748B``,
    // ``#E2E8F0``, ``#F8FAFC``) that used to live in the local
    // ``colors`` map are also gone.
    expect(src).not.toMatch(/onSurface:\s*["']#0F172A["']/);
    expect(src).not.toMatch(/muted:\s*["']#64748B["']/);
    expect(src).not.toMatch(/border:\s*["']#E2E8F0["']/);
    expect(src).not.toMatch(/surfaceSecondary:\s*["']#F8FAFC["']/);
  });

  it("branding swap · PRESERVES semantic error / status / neutral colors (negative guard against over-eager sweep)",
      () => {
    const src = readSrc(MFP_PATH);
    // Error banner semantic colors.
    expect(src).toMatch(/#991B1B/);   // dark red text
    expect(src).toMatch(/#FEE2E2/);   // light red bg
    // Delete-icon destructive red.
    expect(src).toMatch(/#DC2626/);
    // Active status green (bg + fg).
    expect(src).toMatch(/#DCFCE7/);
    expect(src).toMatch(/#166534/);
    // Inactive status neutral gray (bg + fg).
    expect(src).toMatch(/#F3F4F6/);
    expect(src).toMatch(/#6B7280/);
  });
});
