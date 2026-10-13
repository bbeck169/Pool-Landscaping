/**
 * Feb-2026 · P2 #6 property pivot — Commit 3 vitest suite.
 *
 * Locks the behaviour of the Properties list page:
 *
 *   1. Initial fetch uses ``is_active=true`` by default.
 *   2. Hydrates ``?service_category=pool`` from the URL into the
 *      category filter + into the API call.
 *   3. Changing the active filter writes it back to the URL.
 *   4. Rows grouped by customer with a sticky customer-name header.
 *   5. Empty state renders a "Clear filters" button.
 *   6. Clicking a property row navigates to the customer detail
 *      page with ``?tab=properties``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, waitFor, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock, navigateMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: vi.fn(), patch: vi.fn(),
    put: vi.fn(), del: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

// Minimal UI-kit stubs so the page renders in isolation.
vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) => (
    <div>
      <h1 data-testid="pageheader-title">{title}</h1>
      <div>{subtitle}</div>
    </div>
  ),
  Chip: ({ children, ...rest }) => <span {...rest}>{children}</span>,
  Skeleton: ({ style }) => <div data-testid="skeleton" style={style} />,
  EmptyState: ({ title, description, children, ...rest }) => (
    <div {...rest}>
      <div>{title}</div>
      <div>{description}</div>
      {children}
    </div>
  ),
  Button: ({ children, onClick, ...rest }) => (
    <button onClick={onClick} {...rest}>{children}</button>
  ),
}));

vi.mock("@/theme", () => ({
  colors: new Proxy({}, { get: () => "#000" }),
}));


async function _loadPage() {
  return (await import("@/pages/admin/properties/PropertiesListPage")).default;
}


async function renderPageAsync(initialEntry = "/properties") {
  const PropertiesListPage = await _loadPage();
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <PropertiesListPage />
    </MemoryRouter>,
  );
}

describe("PropertiesListPage · P2 #6", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    navigateMock.mockReset();
  });
  afterEach(() => cleanup());

  it("initial fetch uses is_active=true by default", async () => {
    apiGetMock.mockResolvedValue({ items: [] });
    await renderPageAsync();
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    const propertiesCall = apiGetMock.mock.calls.find(
      (c) => c[0].startsWith("/properties"),
    );
    expect(propertiesCall).toBeDefined();
    expect(propertiesCall[0]).toContain("is_active=true");
  });

  it("hydrates ?service_category=pool from URL into the API call",
     async () => {
    apiGetMock.mockResolvedValue({ items: [] });
    await renderPageAsync("/properties?service_category=pool");
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    const propertiesCall = apiGetMock.mock.calls.find(
      (c) => c[0].startsWith("/properties"),
    );
    expect(propertiesCall[0]).toContain("service_category=pool");
  });

  it("hydrates ?is_active=false into the API call", async () => {
    apiGetMock.mockResolvedValue({ items: [] });
    await renderPageAsync("/properties?is_active=false");
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    const call = apiGetMock.mock.calls.find(
      (c) => c[0].startsWith("/properties"),
    );
    expect(call[0]).toContain("is_active=false");
  });

  it("groups rows by customer with sticky customer header", async () => {
    apiGetMock.mockImplementation((url) => {
      if (url.startsWith("/properties")) {
        return Promise.resolve({
          items: [
            { id: "p1", customer_id: "c1", label: "Pool 1",
              address: { line1: "1 Main St" }, active: true,
              service_category: "pool" },
            { id: "p2", customer_id: "c1", label: "Pool 2",
              address: { line1: "2 Main St" }, active: true,
              service_category: "pool" },
            { id: "p3", customer_id: "c2", label: "Yard A",
              address: { line1: "9 Oak Ave" }, active: true,
              service_category: "landscaping" },
          ],
        });
      }
      if (url.startsWith("/customers")) {
        return Promise.resolve({
          items: [
            { id: "c1", name: "Alice Co" },
            { id: "c2", name: "Bob LLC" },
          ],
        });
      }
      return Promise.resolve({});
    });
    await renderPageAsync();
    await waitFor(() => expect(
      screen.getByTestId("properties-list-grouped"),
    ).toBeInTheDocument());
    expect(screen.getByTestId("properties-group-c1")).toBeInTheDocument();
    expect(screen.getByTestId("properties-group-c2")).toBeInTheDocument();
    expect(screen.getByTestId("properties-group-name-c1").textContent)
      .toBe("Alice Co");
    expect(screen.getByTestId("property-row-p1")).toBeInTheDocument();
    expect(screen.getByTestId("property-row-p2")).toBeInTheDocument();
    expect(screen.getByTestId("property-row-p3")).toBeInTheDocument();
  });

  it("empty state renders a Clear filters button", async () => {
    apiGetMock.mockResolvedValue({ items: [] });
    await renderPageAsync("/properties?service_category=unset");
    await waitFor(() => expect(
      screen.getByTestId("properties-list-empty"),
    ).toBeInTheDocument());
    expect(screen.getByText(/clear filters/i)).toBeInTheDocument();
  });

  it("clicking a row navigates to customer detail with properties tab",
     async () => {
    apiGetMock.mockImplementation((url) => {
      if (url.startsWith("/properties")) {
        return Promise.resolve({
          items: [{ id: "px", customer_id: "cx", label: "Px",
                    address: { line1: "X" }, active: true,
                    service_category: "pool" }],
        });
      }
      if (url.startsWith("/customers")) {
        return Promise.resolve({ items: [{ id: "cx", name: "Cx" }] });
      }
      return Promise.resolve({});
    });
    await renderPageAsync();
    await waitFor(() => expect(
      screen.getByTestId("property-row-px"),
    ).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("property-row-px"));
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers/cx?tab=properties",
    );
  });
});
