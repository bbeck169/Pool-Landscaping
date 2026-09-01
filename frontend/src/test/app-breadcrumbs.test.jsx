/**
 * Phase K2 · Feb-2026 — <AppBreadcrumbs> contract.
 *
 * Covers the K2 acceptance criteria:
 *   1. ``/customers/123`` → ``Home > Customers > <display_name>``.
 *   2. ``/portal/messages`` → ``Portal > Messages``.
 *   3. Landing routes (``/dashboard``, ``/portal/home``, ``/``)
 *      render nothing.
 *   4. Last crumb is a ``<BreadcrumbPage>`` — NO ``<a>`` element.
 *   5. Dynamic crumbs whose entity hasn't registered yet render a
 *      ``…`` skeleton.
 *   6. Unmapped path segments fall back to Title-Case.
 *
 * The provider is exported from ``dynamicCrumbContext.jsx``; each
 * test wraps ``AppBreadcrumbs`` in a fresh ``<MemoryRouter>`` +
 * ``<DynamicCrumbProvider>`` so state is isolated.
 */
import React, { useEffect } from "react";
import { describe, it, expect } from "vitest";
import { render, screen, within, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import AppBreadcrumbs
  from "@/components/nav/AppBreadcrumbs";
import { DynamicCrumbProvider, useSetDynamicCrumb }
  from "@/components/nav/dynamicCrumbContext";


function withRoute(path, ui, { withProvider = true } = {}) {
  const wrapped = withProvider
    ? <DynamicCrumbProvider>{ui}</DynamicCrumbProvider>
    : ui;
  return (
    <MemoryRouter initialEntries={[path]}>
      {wrapped}
    </MemoryRouter>
  );
}

// A test-only page mount that registers a dynamic label the same
// way real pages do (``useSetDynamicCrumb`` in an effect).
function CrumbPublisher({ handle, label }) {
  useSetDynamicCrumb(handle, label);
  return null;
}


describe("AppBreadcrumbs · Phase K2 contract", () => {
  it("renders Home > Customers > <display_name> for /customers/:id after the entity registers", async () => {
    await act(async () => {
      render(withRoute("/customers/cust_abc",
        <>
          <AppBreadcrumbs variant="admin" />
          <CrumbPublisher handle="customer" label="Jennifer Carson" />
        </>,
      ));
    });
    const nav = screen.getByTestId("app-breadcrumbs");
    expect(nav).toBeInTheDocument();
    // Chain length = 3 (Home, Customers, Jennifer Carson).
    expect(within(nav).getByTestId("app-breadcrumb-0")).toHaveTextContent("Home");
    expect(within(nav).getByTestId("app-breadcrumb-1")).toHaveTextContent("Customers");
    expect(within(nav).getByTestId("app-breadcrumb-2")).toHaveTextContent("Jennifer Carson");
    // The middle crumb is a link to /customers.
    const customersLink = within(within(nav).getByTestId("app-breadcrumb-1"))
      .getByRole("link");
    expect(customersLink).toHaveAttribute("href", "/customers");
  });

  it("renders Portal > Messages on /portal/messages", async () => {
    await act(async () => {
      render(withRoute("/portal/messages",
        <AppBreadcrumbs variant="portal" />,
      ));
    });
    const nav = screen.getByTestId("app-breadcrumbs");
    expect(nav).toHaveAttribute("data-variant", "portal");
    expect(within(nav).getByTestId("app-breadcrumb-0")).toHaveTextContent("Portal");
    expect(within(nav).getByTestId("app-breadcrumb-1")).toHaveTextContent("Messages");
  });

  it("renders nothing on landing routes (/, /dashboard, /portal/home)", async () => {
    for (const p of ["/", "/dashboard", "/portal/home"]) {
      const { unmount } = render(withRoute(p,
        <AppBreadcrumbs variant="admin" />,
      ));
      expect(screen.queryByTestId("app-breadcrumbs")).toBeNull();
      unmount();
    }
  });

  it("current-page crumb is NOT a link (BreadcrumbPage, no <a>)", async () => {
    await act(async () => {
      render(withRoute("/customers/cust_abc",
        <>
          <AppBreadcrumbs variant="admin" />
          <CrumbPublisher handle="customer" label="Jennifer" />
        </>,
      ));
    });
    const current = screen.getByTestId("app-breadcrumbs-current");
    expect(current).toBeInTheDocument();
    // BreadcrumbPage renders a span with role="link" + aria-disabled;
    // it must NOT be an <a> and must NOT carry an href.
    expect(current.tagName).not.toBe("A");
    expect(current).not.toHaveAttribute("href");
    // aria-current stamp per the shadcn primitive.
    expect(current).toHaveAttribute("aria-current", "page");
  });

  it("shows a ... skeleton for dynamic segments still loading", async () => {
    // No CrumbPublisher mounted → the ``customer`` handle has no
    // registered label → the current-page crumb renders the
    // skeleton chip instead of the generic "Customer".
    await act(async () => {
      render(withRoute("/customers/cust_abc",
        <AppBreadcrumbs variant="admin" />,
      ));
    });
    // Chain length still 3, but the last crumb's rendered content
    // is the skeleton chip.
    const skeleton = screen.getByTestId("app-breadcrumbs-skeleton-2");
    expect(skeleton).toBeInTheDocument();
    // Skeleton content is a literal "…" glyph (aria-labelled for
    // screen readers).
    expect(skeleton).toHaveAttribute("aria-label", "Loading page name");
    expect(skeleton.textContent).toMatch(/…/);
    // The placeholder "Customer" MUST NOT be visible while loading.
    expect(within(screen.getByTestId("app-breadcrumbs"))
      .queryByText("Customer")).toBeNull();
  });

  it("unmapped path segments fall back to Title-Case", async () => {
    // ``/foo-bar/whatever-thing`` doesn't exist in ROUTE_META — the
    // resolver title-cases each segment.
    await act(async () => {
      render(withRoute("/foo-bar/whatever-thing",
        <AppBreadcrumbs variant="admin" />,
      ));
    });
    const nav = screen.getByTestId("app-breadcrumbs");
    // Only the last-segment chip renders (no parent chain since
    // no META entry exists), so we assert on the last-crumb text.
    // Title-Case check: "Whatever Thing" (not "whatever-thing").
    expect(nav).toHaveTextContent(/Whatever Thing/);
  });

  it("carries the nav aria-label='breadcrumb' for a11y", async () => {
    await act(async () => {
      render(withRoute("/customers",
        <AppBreadcrumbs variant="admin" />,
      ));
    });
    // The shadcn primitive stamps ``aria-label`` on the outer
    // ``<nav>`` — screen readers announce "breadcrumb navigation".
    const navByRole = screen.getByRole("navigation",
                                                 { name: /breadcrumb/i });
    expect(navByRole).toBeInTheDocument();
  });
});
