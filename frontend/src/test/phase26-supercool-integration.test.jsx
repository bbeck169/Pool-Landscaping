/**
 * Phase 26 · Feb-2026 · Supercool MCP integration page — vitest.
 *
 * Covers:
 * - Disconnected initial render: status card + Connect CTA visible.
 * - Connect click POSTs /integrations/supercool/connect and triggers
 *   a window.location redirect to the authorize URL.
 * - Connected state renders Refresh + Disconnect controls + tool count.
 * - Refresh catalog POSTs and expands the tool list.
 * - Disconnect confirms + POSTs.
 * - ?connected=1 query param triggers a success toast + status refetch.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(), apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: apiGetMock, post: apiPostMock },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("@/components/layout/SafeScrollContainer", () => ({
  __esModule: true,
  default: ({ children, ...rest }) => <div {...rest}>{children}</div>,
}));


const DISCONNECTED_STATUS = {
  connected: false, tool_count: 0, connected_at: null,
  server_url: "https://mcp.supercool.com/mcp",
};

const CONNECTED_STATUS = {
  connected: true, tool_count: 3,
  connected_at: "2026-02-01T10:00:00Z",
  server_url: "https://mcp.supercool.com/mcp",
};

const EMPTY_CATALOG = { tools: [], fetched_at: null };


beforeEach(() => {
  apiGetMock.mockReset(); apiPostMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});


describe("Phase 26 · Supercool integration page", () => {
  it("renders the disconnected state with a Connect CTA", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve(DISCONNECTED_STATUS);
      if (path === "/integrations/supercool/catalog")
        return Promise.resolve(EMPTY_CATALOG);
      return Promise.resolve({});
    });

    const { default: Page } = await import(
      "@/pages/settings/integrations/SupercoolIntegrationPage"
    );
    render(<MemoryRouter><Page /></MemoryRouter>);
    expect(await screen.findByTestId("supercool-integration-page"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("supercool-page-title"))
      .toHaveTextContent(/Supercool AI/i);
    expect(await screen.findByTestId("supercool-status-badge-disconnected"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("supercool-connect-btn"))
      .toBeInTheDocument();
  });

  it("Connect click POSTs and redirects the browser to authorize_url", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve(DISCONNECTED_STATUS);
      if (path === "/integrations/supercool/catalog")
        return Promise.resolve(EMPTY_CATALOG);
      return Promise.resolve({});
    });
    apiPostMock.mockResolvedValue({
      authorize_url: "https://mcp.supercool.com/authorize?client_id=x&state=abc",
      state: "abc",
      redirect_uri: "https://app.plofv.com/api/integrations/supercool/callback",
    });

    // Trap window.location.href assignments.
    const originalHref = window.location.href;
    let assignedTo = "";
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { get href() { return originalHref; },
                set href(v) { assignedTo = v; } },
      writable: true,
    });

    const { default: Page } = await import(
      "@/pages/settings/integrations/SupercoolIntegrationPage"
    );
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("supercool-integration-page");

    fireEvent.click(await screen.findByTestId("supercool-connect-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/integrations/supercool/connect", {}));
    await waitFor(() =>
      expect(assignedTo).toBe(
        "https://mcp.supercool.com/authorize?client_id=x&state=abc"));
  });

  it("connected state shows Refresh + Disconnect + tool count", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve(CONNECTED_STATUS);
      if (path === "/integrations/supercool/catalog")
        return Promise.resolve({
          tools: [
            { name: "image.generate", description: "generate an image",
              input_schema: { type: "object" } },
          ],
          fetched_at: "2026-02-01T11:00:00Z",
        });
      return Promise.resolve({});
    });

    const { default: Page } = await import(
      "@/pages/settings/integrations/SupercoolIntegrationPage"
    );
    render(<MemoryRouter><Page /></MemoryRouter>);
    expect(await screen.findByTestId("supercool-status-badge-connected"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("supercool-tool-count"))
      .toHaveTextContent("3");
    expect(await screen.findByTestId("supercool-refresh-catalog-btn"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("supercool-disconnect-btn"))
      .toBeInTheDocument();
  });

  it("Refresh Tool Catalog posts + shows tools when expanded", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve(CONNECTED_STATUS);
      if (path === "/integrations/supercool/catalog")
        return Promise.resolve(EMPTY_CATALOG);
      return Promise.resolve({});
    });
    apiPostMock.mockResolvedValue({
      ok: true, tool_count: 2,
      fetched_at: "2026-02-01T12:00:00Z",
      tools: [
        { name: "image.generate", description: "gen image",
          input_schema: { type: "object" } },
        { name: "video.generate", description: "gen video",
          input_schema: { type: "object" } },
      ],
    });

    const { default: Page } = await import(
      "@/pages/settings/integrations/SupercoolIntegrationPage"
    );
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("supercool-integration-page");

    fireEvent.click(await screen.findByTestId("supercool-refresh-catalog-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/integrations/supercool/refresh-catalog", {}));
    expect(await screen.findByTestId("supercool-catalog-tool-0"))
      .toHaveTextContent("image.generate");
    expect(await screen.findByTestId("supercool-catalog-tool-1"))
      .toHaveTextContent("video.generate");
  });

  it("Disconnect flow confirms then posts", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve(CONNECTED_STATUS);
      if (path === "/integrations/supercool/catalog")
        return Promise.resolve(EMPTY_CATALOG);
      return Promise.resolve({});
    });
    apiPostMock.mockResolvedValue({ ok: true });

    const { default: Page } = await import(
      "@/pages/settings/integrations/SupercoolIntegrationPage"
    );
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("supercool-disconnect-btn");
    fireEvent.click(screen.getByTestId("supercool-disconnect-btn"));

    expect(await screen.findByTestId("supercool-disconnect-modal"))
      .toBeInTheDocument();
    fireEvent.click(screen.getByTestId("supercool-disconnect-confirm"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/integrations/supercool/disconnect", {}));
  });

  it("?connected=1 shows a success toast", async () => {
    const { toast } = await import("sonner");
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve(CONNECTED_STATUS);
      if (path === "/integrations/supercool/catalog")
        return Promise.resolve(EMPTY_CATALOG);
      return Promise.resolve({});
    });

    const { default: Page } = await import(
      "@/pages/settings/integrations/SupercoolIntegrationPage"
    );
    render(
      <MemoryRouter initialEntries={["/settings/integrations/supercool?connected=1"]}>
        <Page />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        expect.stringMatching(/Supercool connected/i)));
  });
});
