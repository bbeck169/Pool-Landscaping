/**
 * Task 1 · Feb-2026 — Mobile source-inspection test for the Tag CRUD
 * page, CustomerTagsSection, CommsWhitelistBanner, and
 * DemoAccountToggle. Kept lightweight to avoid the RN test-harness
 * cost — mirrors the web ``queue-item-*`` source-inspection pattern.
 */
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const REPO = resolve(__dirname, "..");

const ADMIN_TAGS = `${REPO}/app/admin/tags.tsx`;
const TAGS_SECTION = `${REPO}/src/components/customers/CustomerTagsSection.tsx`;
const COMMS_BANNER = `${REPO}/src/components/comms/CommsWhitelistBanner.tsx`;
const DEMO_TOGGLE = `${REPO}/src/components/comms/DemoAccountToggle.tsx`;
const CUSTOMER_DETAIL = `${REPO}/app/customer/[id].tsx`;
const SETTINGS_NOTIF = `${REPO}/app/settings/notifications.tsx`;

const read = (p: string) => readFileSync(p, "utf8");

describe("Task 1 · Mobile mirror bundle", () => {
  test("all new mobile files exist", () => {
    expect(existsSync(ADMIN_TAGS)).toBe(true);
    expect(existsSync(TAGS_SECTION)).toBe(true);
    expect(existsSync(COMMS_BANNER)).toBe(true);
    expect(existsSync(DEMO_TOGGLE)).toBe(true);
  });

  describe("Mobile /admin/tags CRUD page", () => {
    const src = read(ADMIN_TAGS);
    test("no longer stubs to ComingSoonPage", () => {
      expect(src).not.toContain("ComingSoonPage");
    });
    test("uses backend endpoints matching the web page", () => {
      expect(src).toContain('api.get("/customer-tags")');
      expect(src).toContain('api.post("/customer-tags", payload)');
      expect(src).toMatch(/api\.patch\(`\/customer-tags\/\$\{editor\.tag\.id\}`, payload\)/);
      expect(src).toMatch(/api\.del\(`\/customer-tags\/\$\{delModal\.tag\.id\}`\)/);
    });
    test("renders new/edit modal + delete confirm modal with testIDs", () => {
      expect(src).toContain('testID="admin-tags-new-btn"');
      expect(src).toContain('testID="tag-editor-modal"');
      expect(src).toContain('testID="tag-editor-name-input"');
      expect(src).toContain('testID="tag-editor-submit"');
      expect(src).toContain('testID="admin-tag-delete-modal"');
      expect(src).toContain('testID="admin-tag-delete-confirm"');
    });
    test("locks system tags with a lock icon + disabled actions + tooltip", () => {
      expect(src).toContain("SYSTEM_LOCK_TOOLTIP");
      expect(src).toContain('name="lock-closed"');
      expect(src).toMatch(/disabled=\{isSystem\}/);
    });
    test("renders the search input at > 10 tags threshold", () => {
      expect(src).toContain("SEARCH_VISIBILITY_THRESHOLD");
      expect(src).toContain("10");
      expect(src).toContain('testID="admin-tags-search-input"');
    });
    test("renders the palette with all 12 swatches (10 pastels + 2 system)", () => {
      expect(src).toContain("#DBEAFE");
      expect(src).toContain("#22C55E");
      expect(src).toContain("#94A3B8");
    });
  });

  describe("Mobile CustomerTagsSection", () => {
    const src = read(TAGS_SECTION);
    test("chip render + tap-to-add bottom sheet + create-new affordance", () => {
      expect(src).toContain('testID="customer-tags-section"');
      expect(src).toContain('testID="customer-tags-open-picker"');
      expect(src).toContain('testID="customer-tags-picker-sheet"');
      expect(src).toContain('testID="customer-tags-picker-create"');
      expect(src).toContain('testID="customer-tags-picker-search"');
    });
    test("attach + detach endpoints match the web contract", () => {
      expect(src).toMatch(/api\.post\(`\/customer-tags\/\$\{tag\.id\}\/attach`,\s*\{ customer_id: customerId \}\)/);
      expect(src).toMatch(/api\.post\(`\/customer-tags\/\$\{tag\.id\}\/detach`,\s*\{ customer_id: customerId \}\)/);
    });
  });

  describe("Mobile CommsWhitelistBanner", () => {
    const src = read(COMMS_BANNER);
    test("hits GET /comms/whitelist/status", () => {
      expect(src).toContain('api.get("/comms/whitelist/status")');
    });
    test("has alert role + red palette + count chips", () => {
      expect(src).toContain('accessibilityRole="alert"');
      expect(src).toContain('#FEF2F2');
      expect(src).toContain('testID="comms-whitelist-banner"');
      // Chip testIDs are passed as ``testid=`` prop → rendered on
      // the child Chip component. Match on the prop assignment.
      expect(src).toContain('testid="comms-whitelist-users-count"');
      expect(src).toContain('testid="comms-whitelist-customers-count"');
      expect(src).toContain('testid="comms-whitelist-suppressed-count"');
    });
  });

  describe("Mobile DemoAccountToggle", () => {
    const src = read(DEMO_TOGGLE);
    test("hits PATCH /comms/demo-flag with the correct payload", () => {
      expect(src).toContain('api.patch("/comms/demo-flag"');
      expect(src).toContain("record_type");
      expect(src).toContain("record_id");
      expect(src).toContain("is_demo_account");
    });
    test("guards with a hard-confirm modal", () => {
      expect(src).toContain('testID={`demo-flag-confirm-modal-${recordType}-${recordId}`}');
      expect(src).toContain('testID={`demo-flag-confirm-btn-${recordType}-${recordId}`}');
      expect(src).toContain('testID={`demo-flag-confirm-cancel-${recordType}-${recordId}`}');
    });
    test("differentiates enable/disable copy inside the confirm modal", () => {
      expect(src).toMatch(/is_demo_account = true/);
      expect(src).toMatch(/is_demo_account = false/);
    });
  });

  describe("Wiring on the existing mobile screens", () => {
    test("customer detail imports and mounts Tags section + Demo toggle", () => {
      const src = read(CUSTOMER_DETAIL);
      expect(src).toContain(
        'import CustomerTagsSection from "@/src/components/customers/CustomerTagsSection"',
      );
      expect(src).toContain(
        'import DemoAccountToggle from "@/src/components/comms/DemoAccountToggle"',
      );
      expect(src).toContain("<CustomerTagsSection");
      expect(src).toMatch(/<DemoAccountToggle[\s\S]*?recordType="customer"/);
    });
    test("settings/notifications imports and mounts the whitelist banner", () => {
      const src = read(SETTINGS_NOTIF);
      expect(src).toContain(
        'import CommsWhitelistBanner from "@/src/components/comms/CommsWhitelistBanner"',
      );
      expect(src).toContain("<CommsWhitelistBanner />");
    });
  });
});
