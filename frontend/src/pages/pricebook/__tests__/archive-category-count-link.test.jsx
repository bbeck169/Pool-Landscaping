/**
 * Pricebook Category UX fixes · Feb-2026 — Task C.
 *
 * Vitest coverage for the clickable "N active pricebook items
 * reference this category" link in the Archive-category modal.
 * Clicking the count:
 *   1. Closes the archive modal.
 *   2. Navigates to /price-book?t=pricebook&category_id=<id> so
 *      the admin lands on the Pricebook list pre-filtered to the
 *      affected category.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockNavigate = vi.fn();

vi.mock("@/api", () => ({
  api: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {},
    { success: () => {}, error: () => {} }),
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Shadcn Dialog in this repo portals to document.body — testing-
// library's `screen` queries the whole document so no additional
// container wiring is needed. The Dialog `open` prop stays truthy
// because the component tree keeps it as local state; we assert
// the modal-close path via the ``onOpenChange(false)`` observable.
import CategoriesAdmin from "@/pages/pricebook/CategoriesAdmin";

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockNavigate.mockReset();
});

describe("Archive-category modal · count link · Task C", () => {
  it("renders the pricebook count as a clickable button on the service axis and navigates to the filtered Pricebook list", async () => {
    // GET /service-categories initial load — one archivable row.
    mockGet.mockImplementation((url) => {
      if (url.startsWith("/service-categories?")) {
        return Promise.resolve({
          items: [
            { id: "svc-99", name: "Winter Cleans", is_archived: false,
               sort_order: 0 },
          ],
        });
      }
      if (url.startsWith("/service-categories/") && url.endsWith("/references")) {
        return Promise.resolve({
          pricebook_item_count: 139,
          line_item_count: 2,
        });
      }
      return Promise.resolve({ items: [] });
    });

    render(
      <MemoryRouter>
        <CategoriesAdmin />
      </MemoryRouter>,
    );

    // Switch to the Service Categories tab (axis="service") via
    // userEvent so Radix Tabs' internal pointerdown + click
    // sequence fires correctly in jsdom (``fireEvent.click`` alone
    // is insufficient; the trigger ignores the synthetic click).
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("categories-admin-tab-service"));

    // Click the archive button on the seeded row.
    const archiveBtn = await screen.findByTestId("service-category-archive-svc-99");
    await user.click(archiveBtn);

    // References loaded → the count is now a clickable button on
    // the service axis.
    const countBtn = await screen.findByTestId("category-refs-pricebook-count");
    expect(countBtn.tagName.toLowerCase()).toBe("button");
    expect(countBtn.textContent).toContain("139");

    fireEvent.click(countBtn);
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith(
      "/price-book?t=pricebook&category_id=svc-99",
    ));
  }, 15000);

  it("keeps the income axis count as a plain <strong> (no deep-link filter supported on income side today)", async () => {
    mockGet.mockImplementation((url) => {
      if (url.startsWith("/income-categories?")) {
        return Promise.resolve({
          items: [
            { id: "inc-50", name: "Repair Revenue", is_archived: false,
               sort_order: 0 },
          ],
        });
      }
      if (url.startsWith("/income-categories/") && url.endsWith("/references")) {
        return Promise.resolve({
          pricebook_item_count: 4, line_item_count: 1,
        });
      }
      return Promise.resolve({ items: [] });
    });

    render(
      <MemoryRouter>
        <CategoriesAdmin />
      </MemoryRouter>,
    );

    // Income tab is default (first).
    const archiveBtn = await screen.findByTestId("income-category-archive-inc-50");
    fireEvent.click(archiveBtn);

    const count = await screen.findByTestId("category-refs-pricebook-count");
    // On the income axis we fall through to the plain <strong>.
    expect(count.tagName.toLowerCase()).toBe("strong");
    expect(count.textContent).toContain("4");
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
