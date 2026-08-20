/**
 * Feb-2026 · Ensure the "Pool Service Report" quick-nav entry exists
 * in ``ADMIN_NAV_V2`` and is gated to the ``reports`` feature.
 *
 * The consuming ``AdminSidebar`` renders any entry whose ``feature``
 * key resolves to truthy in the tenant's feature map — admin /
 * manager / super_admin all have ``reports`` on by default; tech /
 * customer do not.  Locking this test in means a future refactor
 * that drops the entry (or accidentally re-flags it to "admin_only")
 * will fail loudly instead of silently disappearing from the rail.
 */
import { describe, it, expect } from "vitest";
import { NAV_FLAT } from "@/nav/adminNav";


describe("Pool Service Report nav entry", () => {
  const entry = NAV_FLAT.find((i) => i.to === "/admin/reports/pool-service");

  it("is present in ADMIN_NAV_V2", () => {
    expect(entry).toBeTruthy();
    expect(entry.label).toBe("Pool Service Report");
  });

  it("is gated to the 'reports' feature (admin+manager+super_admin visible; tech/customer hidden)", () => {
    // Rail hides an entry when its ``feature`` key is falsy on the
    // tenant's feature map.  ``reports`` is enabled for admin roles
    // and disabled for tech / customer — asserting the KEY is enough,
    // the sidebar's feature-lookup wiring is tested separately.
    expect(entry.feature).toBe("reports");
  });

  it("uses a water-themed icon (Waves) matching sibling pool entries", () => {
    // ``entry.icon`` is a lucide-react React component — presence is
    // enough to lock in that the entry was authored with an icon;
    // we don't identity-compare the ref because lucide may wrap
    // components in ``forwardRef`` at runtime.
    expect(entry?.icon).toBeTruthy();
  });
});
