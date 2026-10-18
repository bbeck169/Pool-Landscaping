/**
 * Portal-Contrast · Feb-2026 — Input/Textarea/Select variant lock.
 *
 * Pre-fix state: Service Reports search / Service-Type / date
 * fields, Reviews comments textarea, Portal Home Request-Service
 * modal + AI composer, Portal Chats composer + new-message modal,
 * Portal Pages (Request Service + email-change confirm +
 * conversations composer), and PortalReviewSubmit textarea all
 * shipped `style={{ backgroundColor: colors.surface, border:
 * '1px solid ${colors.border}' }}` or `backgroundColor:
 * colors.surfaceSecondary` where `colors` was `portalColors` —
 * resolving to deep-navy #03002e / #0a0940 on a deep-navy page
 * surface, rendering typed text + placeholder as dark-on-dark.
 *
 * Fix: a shared `.portal-input` CSS variant scoped under
 * `.portal-dark` paints the control white with navy-900 text,
 * slate-300 border, slate-500 placeholder, and a visible blue
 * focus ring (see `@/styles/portal-dark.css`).
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.join(process.cwd(), "src", rel), "utf-8");

const PORTAL_DARK_CSS = read("styles/portal-dark.css");

/**
 * Locate the inner slice of the JSX element that carries
 * `data-testid="<tid>"` by walking backwards from the testid hit
 * to the nearest preceding `<input`, `<textarea`, or `<select`,
 * then forward to the first `/>` or `</tag>` close.  Returns the
 * raw text slice (open tag through close tag) or `null` when no
 * open-tag anchor is found upstream.
 */
function elementSlice(src, tid) {
  const needle = `data-testid="${tid}"`;
  const idx = src.indexOf(needle);
  if (idx === -1) return null;
  // Nearest preceding open tag of input|textarea|select.
  const openers = ["<input", "<textarea", "<select"];
  let bestOpen = -1;
  for (const o of openers) {
    const i = src.lastIndexOf(o, idx);
    if (i > bestOpen) bestOpen = i;
  }
  if (bestOpen === -1) return null;
  // Forward close — the first `/>` after the testid, or the
  // first `</(input|textarea|select)>` after the testid.
  const closeSelf = src.indexOf("/>", idx);
  const closeTxt = src.indexOf("</", idx);
  let end;
  if (closeSelf !== -1 && (closeTxt === -1 || closeSelf < closeTxt)) {
    end = closeSelf + 2;
  } else if (closeTxt !== -1) {
    end = src.indexOf(">", closeTxt) + 1;
  } else {
    return null;
  }
  return src.slice(bestOpen, end);
}

// ────────────────────────────────────────────────────────────────
// 1. CSS variant contract.
// ────────────────────────────────────────────────────────────────
describe("Portal-Contrast · `.portal-input` CSS variant", () => {
  it("portal-dark.css ships `.portal-dark .portal-input` with white bg + navy-900 text + slate-300 border", () => {
    const idx = PORTAL_DARK_CSS.indexOf(".portal-dark .portal-input");
    expect(idx, "`.portal-dark .portal-input` rule missing").toBeGreaterThan(-1);
    const block = PORTAL_DARK_CSS.slice(idx, idx + 600);
    expect(block).toMatch(/background-color:\s*#FFFFFF\s*!important/i);
    expect(block).toMatch(/color:\s*#0F172A\s*!important/i);
    expect(block).toMatch(/border:\s*1px solid #CBD5E1\s*!important/i);
  });

  it("placeholder paints slate-500 (readable on white — ≥ 4.5:1 WCAG AA)", () => {
    expect(PORTAL_DARK_CSS).toMatch(
      /\.portal-dark \.portal-input::placeholder[\s\S]{0,120}color:\s*#64748B\s*!important/i,
    );
  });

  it("focus ring is a visible blue (#3B82F6) outline + border", () => {
    const idx = PORTAL_DARK_CSS.indexOf(".portal-dark .portal-input:focus");
    expect(idx).toBeGreaterThan(-1);
    const block = PORTAL_DARK_CSS.slice(idx, idx + 400);
    expect(block).toMatch(/border-color:\s*#3B82F6\s*!important/i);
    expect(block).toMatch(/box-shadow:\s*0 0 0 2px/i);
  });

  it("disabled state uses light-gray slate-100 bg + muted slate-500 text (never dark-on-dark)", () => {
    const idx = PORTAL_DARK_CSS.indexOf(".portal-dark .portal-input:disabled");
    expect(idx).toBeGreaterThan(-1);
    const block = PORTAL_DARK_CSS.slice(idx, idx + 400);
    expect(block).toMatch(/background-color:\s*#F1F5F9\s*!important/i);
    expect(block).toMatch(/color:\s*#64748B\s*!important/i);
  });
});

// ────────────────────────────────────────────────────────────────
// 2. Per-page call-site locks — every reported-broken control now
//    ships `portal-input` and no inline dark-navy bg.
// ────────────────────────────────────────────────────────────────
const PAGES = {
  "pages/portal/PortalServiceReports.jsx": [
    // TD-75 · Feb-2026 — ``sr-list-search`` removed from this page
    // per operator directive. Service-type + date filters remain.
    "sr-list-filter-service-type",
    "sr-list-filter-from",
    "sr-list-filter-to",
  ],
  "pages/portal/PortalReviews.jsx": ["portal-review-comment"],
  "pages/portal/PortalHome.jsx": [
    "portal-request-service-type",
    "portal-request-service-date",
    "portal-request-service-notes",
    "portal-ai-composer-input",
  ],
  "pages/portal/PortalChatsPage.jsx": [
    "portal-chats-input",
    "chat-new-subject",
    "chat-new-body",
  ],
  "pages/portal/PortalPages.jsx": [
    "msg-input",
    "rs-details",
    "portal-profile-confirm-current-email",
  ],
  "pages/portal/PortalReviewSubmit.jsx": ["review-text"],
};

describe("Portal-Contrast · migrated controls ship `portal-input` className", () => {
  for (const [rel, tids] of Object.entries(PAGES)) {
    const SRC = read(rel);
    for (const tid of tids) {
      it(`${rel} :: ${tid} control ships portal-input className`, () => {
        const slice = elementSlice(SRC, tid);
        expect(slice, `${tid} not found in ${rel}`).not.toBeNull();
        expect(slice).toMatch(/className=["'][^"']*\bportal-input\b/);
      });
    }
  }
});

describe("Portal-Contrast · migrated controls shed dark-navy inline bg literals", () => {
  for (const [rel, tids] of Object.entries(PAGES)) {
    const SRC = read(rel);
    for (const tid of tids) {
      it(`${rel} :: ${tid} control carries no inline dark-navy bg`, () => {
        const slice = elementSlice(SRC, tid);
        expect(slice, `${tid} not found in ${rel}`).not.toBeNull();
        // No dark-on-dark literal survives on this control.
        expect(slice).not.toMatch(/backgroundColor:\s*colors\.surface/);
        expect(slice).not.toMatch(/background:\s*colors\.surface/);
        expect(slice).not.toMatch(/backgroundColor:\s*colors\.surfaceSecondary/);
        expect(slice).not.toMatch(/backgroundColor:\s*colors\.background\b/);
      });
    }
  }
});

// ────────────────────────────────────────────────────────────────
// 3. Snapshot a representative className for `<input>`, `<textarea>`,
//    `<select>` so a silent class drop is noisy.
// ────────────────────────────────────────────────────────────────
describe("Portal-Contrast · representative className snapshot per element shape", () => {
  it("representative <input> (sr-list-filter-service-type) className contains portal-input first", () => {
    const SRC = read("pages/portal/PortalServiceReports.jsx");
    // TD-75 · Feb-2026 — representative anchor swapped from the
    // removed ``sr-list-search`` to the retained Service-Type input.
    const slice = elementSlice(SRC, "sr-list-filter-service-type");
    expect(slice).not.toBeNull();
    const m = slice.match(/className=["']([^"']+)["']/);
    expect(m).not.toBeNull();
    expect(m[1].split(/\s+/)[0]).toBe("portal-input");
  });

  it("representative <textarea> (portal-review-comment) className contains portal-input first", () => {
    const SRC = read("pages/portal/PortalReviews.jsx");
    const slice = elementSlice(SRC, "portal-review-comment");
    expect(slice).not.toBeNull();
    const m = slice.match(/className=["']([^"']+)["']/);
    expect(m).not.toBeNull();
    expect(m[1].split(/\s+/)[0]).toBe("portal-input");
  });

  it("representative <select> (portal-request-service-type) className contains portal-input first", () => {
    const SRC = read("pages/portal/PortalHome.jsx");
    const slice = elementSlice(SRC, "portal-request-service-type");
    expect(slice).not.toBeNull();
    const m = slice.match(/className=["']([^"']+)["']/);
    expect(m).not.toBeNull();
    expect(m[1].split(/\s+/)[0]).toBe("portal-input");
  });
});
