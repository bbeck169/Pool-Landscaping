import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path === "/tenants/current") {
        return { id: "T1", slug: "aquaterra", name: "Aquaterra" };
      }
      return {};
    }),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin",
                              tenant: { slug: "aquaterra" } } }),
}));

import WidgetEmbedPage from "@/pages/admin/WidgetEmbedPage";

describe("WidgetEmbedPage", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("renders page shell + snippet", async () => {
    render(<MemoryRouter><WidgetEmbedPage /></MemoryRouter>);
    expect(screen.getByTestId("widget-embed-page")).toBeTruthy();
    expect(screen.getByTestId("widget-embed-title")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("widget-embed-snippet").textContent).toContain(`data-tenant="aquaterra"`);
    });
  });

  it("renders the preview iframe pointing at /widget/preview/<slug>", async () => {
    render(<MemoryRouter><WidgetEmbedPage /></MemoryRouter>);
    await waitFor(() => {
      const iframe = screen.getByTestId("widget-embed-iframe");
      expect(iframe.getAttribute("src")).toContain("/api/widget/preview/aquaterra");
      expect(iframe.getAttribute("src")).toContain("theme=light");
    });
  });

  it("changing theme updates the iframe src", async () => {
    render(<MemoryRouter><WidgetEmbedPage /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("widget-embed-iframe"));
    fireEvent.change(screen.getByTestId("widget-embed-theme"),
                       { target: { value: "dark" } });
    await waitFor(() => {
      const iframe = screen.getByTestId("widget-embed-iframe");
      expect(iframe.getAttribute("src")).toContain("theme=dark");
    });
    // And the snippet reflects the change too.
    expect(screen.getByTestId("widget-embed-snippet").textContent).toContain(`data-theme="dark"`);
  });

  it("copy button writes the snippet to clipboard", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MemoryRouter><WidgetEmbedPage /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("widget-embed-copy"));
    fireEvent.click(screen.getByTestId("widget-embed-copy"));
    await waitFor(() => { expect(writeText).toHaveBeenCalled(); });
    const arg = writeText.mock.calls[0][0];
    expect(arg).toContain("data-tenant=\"aquaterra\"");
    expect(arg).toContain("widget.js");
  });
});
