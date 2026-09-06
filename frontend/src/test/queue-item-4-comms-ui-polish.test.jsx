// Queue Item 4 · Feb-2026 — source-inspection vitest for the
// Outbound Comms UI polish work:
//   • CommsWhitelistBanner with live counts
//   • DemoAccountToggle with hard-confirm modal
//   • AdminCommsSuppressionLog paginated + filterable viewer
//   • Route registration (super_admin gate) in App.js
//   • Banner mounted on /settings/notifications
//   • Toggle mounted on customer detail + admin users
//   • Nav link exposed to super_admins
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const BANNER = resolve(__dirname, "../components/comms/CommsWhitelistBanner.jsx");
const TOGGLE = resolve(__dirname, "../components/comms/DemoAccountToggle.jsx");
const LOG_PAGE = resolve(__dirname, "../pages/admin/AdminCommsSuppressionLog.jsx");
const APP = resolve(__dirname, "../App.js");
const NOTIF = resolve(__dirname, "../pages/settings/NotificationPrefs.jsx");
const CUSTOMER_DETAIL = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");
const ADMIN_USERS = resolve(__dirname, "../pages/admin/AdminUsersList.jsx");
const ADMIN_NAV = resolve(__dirname, "../nav/adminNav.js");

const read = (p) => readFileSync(p, "utf8");

describe("Queue Item 4 · Comms UI polish", () => {
  it("all three new files exist at the expected paths", () => {
    expect(existsSync(BANNER)).toBe(true);
    expect(existsSync(TOGGLE)).toBe(true);
    expect(existsSync(LOG_PAGE)).toBe(true);
  });

  describe("CommsWhitelistBanner", () => {
    const src = read(BANNER);
    it("hits GET /comms/whitelist/status", () => {
      expect(src).toContain('api.get("/comms/whitelist/status")');
    });
    it("renders red safety copy + live counts", () => {
      expect(src).toContain('data-testid="comms-whitelist-banner"');
      expect(src).toContain('data-testid="comms-whitelist-banner-counts"');
      expect(src).toContain('testid="comms-whitelist-users-count"');
      expect(src).toContain('testid="comms-whitelist-customers-count"');
      expect(src).toContain('testid="comms-whitelist-suppressed-count"');
      // Red pallette + role="alert" hint.
      expect(src).toContain('#FEF2F2');
      expect(src).toContain('role="alert"');
    });
  });

  describe("DemoAccountToggle", () => {
    const src = read(TOGGLE);
    it("PATCHes /comms/demo-flag with the correct payload keys", () => {
      expect(src).toContain('api.patch("/comms/demo-flag"');
      expect(src).toContain("record_type");
      expect(src).toContain("record_id");
      expect(src).toContain("is_demo_account");
    });
    it("guards flip with a hard-confirm modal (no soft dismiss)", () => {
      // Modal component uses a stateful open flag; confirm + cancel
      // callbacks each own an explicit testID.
      expect(src).toMatch(/demo-flag-confirm-modal-\$\{recordType\}-\$\{recordId\}/);
      expect(src).toMatch(/demo-flag-confirm-btn-\$\{recordType\}-\$\{recordId\}/);
      expect(src).toMatch(/demo-flag-confirm-cancel-\$\{recordType\}-\$\{recordId\}/);
    });
    it("differentiates enable vs. disable copy in the confirm modal", () => {
      // The confirm body must not read as generic "toggle" copy.
      expect(src).toMatch(/is_demo_account = true/);
      expect(src).toMatch(/is_demo_account = false/);
    });
  });

  describe("AdminCommsSuppressionLog", () => {
    const src = read(LOG_PAGE);
    it("hits GET /comms/suppression-log with pagination params", () => {
      expect(src).toContain('api.get(`/comms/suppression-log?');
      expect(src).toContain('params.set("limit"');
      expect(src).toContain('params.set("skip"');
    });
    it("exposes type / recipient / provider filters", () => {
      expect(src).toContain('testid="admin-suppression-log-filter-type"');
      expect(src).toContain('testid="admin-suppression-log-filter-recipient"');
      expect(src).toContain('testid="admin-suppression-log-filter-provider"');
    });
    it("shows table, empty-state, and pagination controls", () => {
      expect(src).toContain('data-testid="admin-suppression-log-table"');
      expect(src).toContain('data-testid="admin-suppression-log-empty"');
      expect(src).toContain('data-testid="admin-suppression-log-prev"');
      expect(src).toContain('data-testid="admin-suppression-log-next"');
      expect(src).toContain('data-testid="admin-suppression-log-range"');
    });
    it("embeds the whitelist banner up top", () => {
      expect(src).toContain("<CommsWhitelistBanner />");
    });
  });

  describe("App.js wiring", () => {
    const src = read(APP);
    it("imports the suppression-log page component", () => {
      expect(src).toContain(
        'import AdminCommsSuppressionLog from "@/pages/admin/AdminCommsSuppressionLog"',
      );
    });
    it("registers /admin/comms/suppression-log behind SuperAdminOnly", () => {
      expect(src).toMatch(
        /path="admin\/comms\/suppression-log"[^>]*<SuperAdminOnly><AdminCommsSuppressionLog/,
      );
    });
  });

  describe("NotificationPrefs banner mount", () => {
    const src = read(NOTIF);
    it("imports and renders the banner", () => {
      expect(src).toContain(
        'import CommsWhitelistBanner from "@/components/comms/CommsWhitelistBanner"',
      );
      expect(src).toContain("<CommsWhitelistBanner />");
    });
  });

  describe("CustomerDetail toggle mount", () => {
    const src = read(CUSTOMER_DETAIL);
    it("imports and renders the toggle for the customer", () => {
      expect(src).toContain(
        'import DemoAccountToggle from "@/components/comms/DemoAccountToggle"',
      );
      expect(src).toMatch(/<DemoAccountToggle[\s\S]*?recordType="customer"/);
    });
  });

  describe("AdminUsersList toggle mount", () => {
    const src = read(ADMIN_USERS);
    it("adds a Comms column with the per-user toggle", () => {
      expect(src).toContain(
        'import DemoAccountToggle from "@/components/comms/DemoAccountToggle"',
      );
      expect(src).toMatch(/<DemoAccountToggle[\s\S]*?recordType="user"/);
      // Phase Hygiene B · Feb-2026 — the empty-row colSpan tracks
      // the visible column count, which now sits at 7 (Name, Email,
      // Role, Department, Status, Comms, Actions). Contract: colSpan
      // MUST equal the column count so a "no users" empty state
      // spans the full table width.
      expect(src).toContain('colSpan={7}');
      // "Comms" column header rendered.
      expect(src).toMatch(/>Comms</);
    });
  });

  describe("Admin nav link", () => {
    const src = read(ADMIN_NAV);
    it("exposes the suppression log to super_admins in the nav", () => {
      expect(src).toContain("/admin/comms/suppression-log");
      expect(src).toContain("super_admin_only");
    });
  });
});
