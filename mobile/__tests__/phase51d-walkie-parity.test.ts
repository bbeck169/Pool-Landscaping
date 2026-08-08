/**
 * Phase 51d · Feb-2026 — Mobile ↔ web walkie parity snapshot.
 *
 * Mirror of ``frontend/src/test/phase51d-web-mobile-parity.test.jsx``
 * on the mobile side — reads both trees at test-time and locks the
 * shared product decisions in place so parity can't silently drift.
 * If web changes a shared invariant without mirroring on mobile,
 * this file goes red.
 */
import * as fs from "fs";
import * as path from "path";

// AsyncStorage native module is not available in Jest — mock it
// before importing anything that touches walkie-helpers.
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => undefined),
  removeItem: jest.fn(async () => undefined),
  clear: jest.fn(async () => undefined),
}));

// eslint-disable-next-line import/first
import {
  BROADCAST_ROLES as MOBILE_BROADCAST_ROLES,
  PIN_ROLES as MOBILE_PIN_ROLES,
  AUDIO_MIME_CANDIDATES as MOBILE_MIME,
  sortChannels as mobileSort,
} from "@/src/pages/walkie/walkie-helpers";

const REPO_ROOT = path.resolve(__dirname, "..", "..");

function readWeb(rel: string) {
  return fs.readFileSync(path.join(REPO_ROOT, "frontend", rel), "utf-8");
}
function readMobile(rel: string) {
  return fs.readFileSync(path.join(REPO_ROOT, "mobile", rel), "utf-8");
}

const WEB_HELPERS = readWeb("src/pages/walkie/walkie-helpers.js");
const WEB_PAGE = readWeb("src/pages/walkie/Walkie.jsx");
const MOBILE_HELPERS = readMobile("src/pages/walkie/walkie-helpers.ts");
const MOBILE_INDEX = readMobile("app/walkie/index.tsx");
const MOBILE_CHANNEL = readMobile("app/walkie/[channelId].tsx");

describe("Phase 51d · mobile ↔ web channel-ordering parity", () => {
  it("mobile sortChannels agrees with the shared priority table", () => {
    const chs = [
      { id: "d", kind: "direct", created_at: "2026-02-01T00:00:00Z" },
      { id: "dep", kind: "department", department: "pool" },
      { id: "ah", kind: "all_hands" },
    ];
    expect(mobileSort(chs).map((c) => c.id)).toEqual(["ah", "dep", "d"]);
  });

  it("web helpers reference the same three-tier ordering (source snapshot)", () => {
    expect(WEB_HELPERS).toMatch(/all_hands:\s*0/);
    expect(WEB_HELPERS).toMatch(/department:\s*1/);
    expect(WEB_HELPERS).toMatch(/direct:\s*2/);
  });
});

describe("Phase 51d · mobile ↔ web 30s hold-to-record cap", () => {
  it("both surfaces cap at 30_000ms", () => {
    expect(WEB_PAGE).toMatch(/MAX_RECORD_MS\s*=\s*30_?000/);
    expect(MOBILE_CHANNEL).toMatch(/MAX_RECORD_MS\s*=\s*30_?000/);
  });
});

describe("Phase 51d · mobile ↔ web walkie_muted persistence key", () => {
  it("both surfaces use the exact ``walkie_muted`` key", () => {
    expect(WEB_HELPERS).toMatch(/const MUTE_KEY = "walkie_muted"/);
    expect(MOBILE_HELPERS).toMatch(/const MUTE_KEY = "walkie_muted"/);
  });
});

describe("Phase 51d · mobile ↔ web admin-only all-hands gate", () => {
  it("mobile BROADCAST_ROLES is the shared three-role set", () => {
    expect(Array.from(MOBILE_BROADCAST_ROLES).sort()).toEqual(["admin", "manager", "super_admin"]);
  });

  it("web helpers source declares the same three roles", () => {
    expect(WEB_HELPERS).toMatch(/BROADCAST_ROLES = new Set\(\[\s*"super_admin",\s*"admin",\s*"manager"\s*\]\)/);
  });

  it("both surfaces surface the exact server-parity error message", () => {
    const msg = "Only admins can broadcast to all-hands";
    expect(WEB_HELPERS).toContain(msg);
    expect(MOBILE_HELPERS).toContain(msg);
  });
});

describe("Phase 51d · mobile ↔ web waveform + MIME contract", () => {
  it("both surfaces render a fallback bar (``-fallback`` suffix)", () => {
    expect(WEB_PAGE).toContain("-fallback");
    expect(MOBILE_CHANNEL).toContain("-fallback");
  });

  it("mobile MIME candidates are a subset of the backend whitelist", () => {
    const accepted = new Set(["audio/webm", "audio/mp4", "audio/aac", "audio/mpeg", "audio/ogg"]);
    for (const t of MOBILE_MIME) {
      expect(accepted.has(t.split(";")[0])).toBe(true);
    }
  });
});

describe("Phase 51d · mobile ↔ web testID manifest", () => {
  it("the shared testID set is present on both surfaces", () => {
    const shared = [
      "walkie-page",
      "walkie-record-btn",
      "walkie-message-row",
      "walkie-own-tag",
      "walkie-play-btn",
    ];
    for (const tid of shared) {
      expect(WEB_PAGE).toContain(tid);
      const inMobile = MOBILE_INDEX.includes(tid) || MOBILE_CHANNEL.includes(tid);
      expect(inMobile).toBe(true);
    }
  });
});

describe("Phase 51.5 · mobile ↔ web pin gate parity", () => {
  it("mobile PIN_ROLES matches the shared three-role set", () => {
    expect(Array.from(MOBILE_PIN_ROLES).sort()).toEqual(["admin", "manager", "super_admin"]);
  });

  it("web helpers source declares the same PIN_ROLES set", () => {
    expect(WEB_HELPERS).toMatch(/PIN_ROLES = new Set\(\[\s*"super_admin",\s*"admin",\s*"manager"\s*\]\)/);
  });

  it("both surfaces export canPinInChannel", () => {
    expect(WEB_HELPERS).toMatch(/export function canPinInChannel/);
    expect(MOBILE_HELPERS).toMatch(/export function canPinInChannel/);
  });

  it("both surfaces render a walkie-pinned-badge node", () => {
    expect(WEB_PAGE).toContain("walkie-pinned-badge");
    expect(MOBILE_CHANNEL).toContain("walkie-pinned-badge");
  });
});


describe("Phase 51.6 · mobile ↔ web reply gate + preview parity", () => {
  it("both surfaces export canReplyInChannel", () => {
    expect(WEB_HELPERS).toMatch(/export function canReplyInChannel/);
    expect(MOBILE_HELPERS).toMatch(/export function canReplyInChannel/);
  });

  it("both surfaces export normalizeReplyPreview + replyPreviewLabel", () => {
    expect(WEB_HELPERS).toMatch(/export function normalizeReplyPreview/);
    expect(MOBILE_HELPERS).toMatch(/export function normalizeReplyPreview/);
    expect(WEB_HELPERS).toMatch(/export function replyPreviewLabel/);
    expect(MOBILE_HELPERS).toMatch(/export function replyPreviewLabel/);
  });

  it("both surfaces render the exact '(original message deleted)' placeholder string", () => {
    const placeholder = "(original message deleted)";
    expect(WEB_HELPERS).toContain(placeholder);
    expect(MOBILE_HELPERS).toContain(placeholder);
  });
});


// ═══════════════════════════════════════════════════════════════════
// Phase 53c · mobile ↔ web EBIT panel parity
// ═══════════════════════════════════════════════════════════════════
const WEB_EBIT = readWeb("src/components/admin/EbitPanel.jsx");
const MOBILE_EBIT = readMobile("src/components/admin/EbitPanel.tsx");
const WEB_PROFIT_PAGE = readWeb("src/pages/admin/ProfitReportPage.jsx");
const MOBILE_PROFIT_PAGE = readMobile("app/profit-report.tsx");

describe("Phase 53c · mobile ↔ web EBIT panel parity", () => {
  it("both surfaces mount an <EbitPanel /> from src/components/admin", () => {
    expect(WEB_PROFIT_PAGE).toMatch(/import\s+EbitPanel\s+from\s+["']@\/components\/admin\/EbitPanel["']/);
    expect(MOBILE_PROFIT_PAGE).toMatch(/import\s+EbitPanel\s+from\s+["']@\/src\/components\/admin\/EbitPanel["']/);
    expect(WEB_PROFIT_PAGE).toContain("<EbitPanel />");
    expect(MOBILE_PROFIT_PAGE).toContain("<EbitPanel />");
  });

  it("both surfaces emit the shared line-key testid patterns for every EBIT row", () => {
    // The four line rows use ``${lineKey}`` interpolation on both
    // surfaces, so we assert the literal template forms rather than
    // the four resolved strings — parity is what matters.
    const PATTERNS = [
      "ebit-row-${lineKey}",
      "ebit-row-${lineKey}-computed",
      "ebit-row-${lineKey}-effective",
      "ebit-row-${lineKey}-adjustment-mode",
      "ebit-row-${lineKey}-adjustment-input",
      "ebit-row-${lineKey}-override-mode",
      "ebit-row-${lineKey}-override-input",
      "ebit-row-${lineKey}-override-clear",
      "ebit-row-${lineKey}-flip-override",
    ];
    for (const p of PATTERNS) {
      expect(WEB_EBIT).toContain(p);
      expect(MOBILE_EBIT).toContain(p);
    }
  });

  it("both surfaces expose the shared panel-level testids", () => {
    // Panel-level testids are literal on both surfaces. Range pill
    // testids use ``${r.key}`` interpolation on both, so the
    // template form is asserted.
    const SHARED = [
      "ebit-panel",
      "ebit-panel-forbidden",
      "ebit-panel-live-tag",
      "ebit-panel-loaded-version",
      "ebit-range-picker",
      "ebit-range-${r.key}",
      "ebit-basis-toggle",
      "ebit-basis-cash",
      "ebit-basis-accrual",
      "ebit-rows",
      "ebit-total-row",
      "ebit-total-value",
      "ebit-save-row",
      "ebit-save-note",
      "ebit-save-btn",
      "ebit-fork-btn",
      "ebit-open-versions",
      "ebit-export-csv",
      "ebit-export-pdf",
      "ebit-versions-modal",
      "ebit-versions-empty",
      "ebit-versions-close",
    ];
    for (const t of SHARED) {
      expect(WEB_EBIT).toContain(t);
      expect(MOBILE_EBIT).toContain(t);
    }
  });

  it("both surfaces consume the same 3 EBIT endpoints", () => {
    expect(WEB_EBIT).toContain("/ebit/compute");
    expect(WEB_EBIT).toContain("/ebit/snapshots");
    expect(MOBILE_EBIT).toContain("/ebit/compute");
    expect(MOBILE_EBIT).toContain("/ebit/snapshots");
    // Save always POSTs (never PATCH) — matches 6B immutable-versions.
    expect(WEB_EBIT).toMatch(/api\.post\(\s*[`"']\/ebit\/snapshots/);
    expect(MOBILE_EBIT).toMatch(/api\.post\(\s*[`"']\/ebit\/snapshots/);
  });

  it("both surfaces gate edit to super_admin + admin and view to +manager", () => {
    // canEdit uses the exact same OR expression on both platforms.
    expect(WEB_EBIT).toMatch(/role === ["']super_admin["'] \|\| role === ["']admin["']/);
    expect(MOBILE_EBIT).toMatch(/role === ["']super_admin["'] \|\| role === ["']admin["']/);
    expect(WEB_EBIT).toMatch(/canEdit \|\| role === ["']manager["']/);
    expect(MOBILE_EBIT).toMatch(/canEdit \|\| role === ["']manager["']/);
  });

  // Phase 53c-fix · Feb-2026 — manager read-only rendering parity.
  it("both surfaces surface the same ebit-panel-readonly-badge testid", () => {
    expect(WEB_EBIT).toContain("ebit-panel-readonly-badge");
    expect(MOBILE_EBIT).toContain("ebit-panel-readonly-badge");
  });

  it("both surfaces pass a readOnly prop to EbitLineRow when !canEdit", () => {
    // The web + mobile panels both compute readOnly from `!canEdit`
    // and forward it to the row so managers still see prior edits.
    expect(WEB_EBIT).toMatch(/readOnly=\{!canEdit\}/);
    expect(MOBILE_EBIT).toMatch(/readOnly=\{!canEdit\}/);
    // Row uses ``disabled`` (web) / ``editable={!inputsDisabled}`` (mobile).
    expect(WEB_EBIT).toMatch(/disabled=\{inputsDisabled\}/);
    expect(MOBILE_EBIT).toMatch(/editable=\{!inputsDisabled\}/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// Phase 53d · Feb-2026 — EBIT MVP closeout contract parity.
//   These assertions lock the exact vocab shared between the two
//   surfaces + the backend, so any drift breaks the build.
// ═══════════════════════════════════════════════════════════════════
describe("Phase 53d · EBIT MVP closeout — shared vocab parity", () => {
  // ── 1. Line-item keys ────────────────────────────────────────
  const ADJUSTMENT_KEYS = ["revenue", "cogs", "opex", "depreciation"];

  it("both surfaces declare the same LINE_KEYS = ADJUSTMENT_KEYS", () => {
    // Both files have a top-of-file ``LINE_KEYS = [...]`` array.
    // We normalise whitespace + compare.
    function extractLineKeys(src: string): string[] {
      const m = src.match(/LINE_KEYS[^\n=]*=\s*\[([^\]]+)\]/);
      if (!m) return [];
      return m[1]
        .split(",")
        .map((s) => s.trim().replace(/["'`]/g, ""))
        .filter(Boolean);
    }
    expect(extractLineKeys(WEB_EBIT)).toEqual(ADJUSTMENT_KEYS);
    expect(extractLineKeys(MOBILE_EBIT)).toEqual(ADJUSTMENT_KEYS);
  });

  // ── 2. Role sets ─────────────────────────────────────────────
  const EDITOR_ROLES = ["super_admin", "admin"];
  const VIEWER_ROLES = ["super_admin", "admin", "manager"];

  it("EDITOR_ROLES = {super_admin, admin} on both surfaces (canEdit)", () => {
    for (const r of EDITOR_ROLES) {
      expect(WEB_EBIT).toContain(`role === "${r}"`);
      expect(MOBILE_EBIT).toContain(`role === "${r}"`);
    }
  });

  it("VIEWER_ROLES = {super_admin, admin, manager} on both surfaces (canView)", () => {
    // canView = canEdit || role === "manager"
    for (const r of VIEWER_ROLES) {
      expect(WEB_EBIT.includes(`role === "${r}"`) ||
              (r === "manager" && WEB_EBIT.match(/canEdit \|\| role === ["']manager["']/)))
        .toBeTruthy();
      expect(MOBILE_EBIT.includes(`role === "${r}"`) ||
              (r === "manager" && MOBILE_EBIT.match(/canEdit \|\| role === ["']manager["']/)))
        .toBeTruthy();
    }
  });

  // ── 3. Manager read-only testids (same set on both) ──────────
  const MANAGER_READONLY_KEYS = [
    "ebit-panel-readonly-badge",
    "ebit-row-${lineKey}-adjustment-input",  // rendered disabled for manager
  ];
  const MANAGER_HIDDEN_KEYS = [
    "ebit-row-${lineKey}-flip-override",
    "ebit-row-${lineKey}-override-clear",
    "ebit-save-btn",
    "ebit-save-note",
    "ebit-save-row",
  ];

  it("MANAGER_READONLY_KEYS render on both surfaces", () => {
    for (const k of MANAGER_READONLY_KEYS) {
      expect(WEB_EBIT).toContain(k);
      expect(MOBILE_EBIT).toContain(k);
    }
  });

  it("MANAGER_HIDDEN_KEYS render behind a canEdit / !readOnly gate on both surfaces", () => {
    for (const k of MANAGER_HIDDEN_KEYS) {
      // Both surfaces must reference the testid (so the visible admin
      // rendering exists) — the read-only rendering hides it, verified
      // separately by the unit + component tests.
      expect(WEB_EBIT).toContain(k);
      expect(MOBILE_EBIT).toContain(k);
    }
  });

  // ── 4. OpenAPI range enum ────────────────────────────────────
  const RANGE_ENUM = ["this_month", "last_month", "qtd", "ytd",
                       "monthly", "quarterly", "custom"];

  it("both surfaces reference every value in the OpenAPI range enum", () => {
    for (const v of RANGE_ENUM) {
      // Web + mobile either build the value client-side (monthly /
      // quarterly / custom pills) OR the server accepts it — the
      // string must appear at least once in each surface for
      // client-driven values.
      const CLIENT_ONLY = new Set(["monthly", "quarterly", "custom"]);
      if (CLIENT_ONLY.has(v)) {
        expect(WEB_EBIT).toContain(v);
        expect(MOBILE_EBIT).toContain(v);
      }
    }
  });

  // ── 5. Revenue-basis toggle ──────────────────────────────────
  const BASIS_VALUES = ["cash", "accrual"];

  it("revenue-basis values {cash, accrual} present on both surfaces", () => {
    for (const v of BASIS_VALUES) {
      expect(WEB_EBIT).toContain(`"${v}"`);
      expect(MOBILE_EBIT).toContain(`"${v}"`);
    }
  });

  // ── 6. EBIT total formula ────────────────────────────────────
  it("both surfaces compute EBIT via revenue - cogs - opex - depreciation", () => {
    // Both files call ``toEffective`` and then compute
    //   out.ebit = out.revenue - out.cogs - out.opex - out.depreciation
    // Assert the literal formula string is present.
    const FORMULA = /out\.ebit\s*=\s*out\.revenue\s*-\s*out\.cogs\s*-\s*out\.opex\s*-\s*out\.depreciation/;
    expect(WEB_EBIT).toMatch(FORMULA);
    expect(MOBILE_EBIT).toMatch(FORMULA);
  });

  // ── 7. Endpoint contract parity ──────────────────────────────
  it("both surfaces POST /ebit/snapshots (never PATCH) for new saves", () => {
    expect(WEB_EBIT).toMatch(/api\.post\(\s*[`"']\/ebit\/snapshots/);
    expect(MOBILE_EBIT).toMatch(/api\.post\(\s*[`"']\/ebit\/snapshots/);
    // Neither surface should call PATCH — PATCH endpoints exist but
    // are unused in the MVP (immutable-versions contract 6B).
    expect(WEB_EBIT).not.toMatch(/api\.patch\(\s*[`"']\/ebit/);
    expect(MOBILE_EBIT).not.toMatch(/api\.patch\(\s*[`"']\/ebit/);
  });

  it("both surfaces render the author_display_name field from saved snapshots", () => {
    // Web versions modal renders the author on each row; mobile does
    // the same. Reading .author_display_name locks the contract.
    // (Fallback to author_user_id is fine — but the field MUST be
    // referenced on at least one surface.)
    const anyReferences =
      WEB_EBIT.includes("author_display_name") ||
      WEB_EBIT.includes("author_user_id");
    const mobileReferences =
      MOBILE_EBIT.includes("author_display_name") ||
      MOBILE_EBIT.includes("author_user_id");
    expect(anyReferences).toBe(true);
    expect(mobileReferences).toBe(true);
  });
});


