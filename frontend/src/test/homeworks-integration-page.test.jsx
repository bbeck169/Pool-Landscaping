/**
 * Phase 0 POC · Feb-2026 — HomeworksIntegrationPage tests.
 *
 * Covers:
 *   1. Form fields render with the correct data-testids.
 *   2. GET is called on mount and pre-fills the form.
 *   3. Save button PUTs the correct payload shape.
 *   4. Connect button POSTs and opens authorize_url in a new tab.
 *   5. Smoke test renders tools + sample customer JSON.
 *   6. Disconnected state hides the smoke-test card.
 *   7. Error state surfaces last_error in the status log.
 *   8. Empty client_secret is passed to backend (backend keeps existing).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    put: (...a) => mockPut(...a),
  },
}));

// sonner toast is called; mock so tests don't blow up.
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import HomeworksIntegrationPage from "@/pages/admin/integrations/HomeworksIntegrationPage";


const DISCONNECTED_STATE = {
  tenant_id: "t-poc",
  client_id: "",
  has_client_secret: false,
  authorize_url: "",
  token_url: "",
  redirect_uri: "",
  scopes: [],
  mcp_server_url: "https://www.home.works/connect/mcp",
  connection_status: "disconnected",
  has_access_token: false,
  has_refresh_token: false,
  last_error: null,
  last_connected_at: null,
  token_expires_at: null,
};

const CONNECTED_STATE = {
  ...DISCONNECTED_STATE,
  client_id: "cli-42",
  has_client_secret: true,
  authorize_url: "https://a/oauth/authorize",
  token_url: "https://a/oauth/token",
  redirect_uri: "https://cb/cb",
  scopes: ["read:customers"],
  connection_status: "connected",
  has_access_token: true,
  has_refresh_token: true,
  last_connected_at: "2026-02-15T10:00:00Z",
};


let _openSpy;
const _origOpen = window.open;

beforeEach(() => {
  vi.clearAllMocks();
  _openSpy = vi.fn();
  window.open = _openSpy;
});

afterEach(() => {
  window.open = _origOpen;
});


describe("HomeworksIntegrationPage", () => {
  it("renders all credential form fields with stable testids", async () => {
    mockGet.mockResolvedValue(DISCONNECTED_STATE);
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-page-title")).toBeTruthy();
    });
    expect(screen.getByTestId("homeworks-client-id")).toBeTruthy();
    expect(screen.getByTestId("homeworks-client-secret")).toBeTruthy();
    expect(screen.getByTestId("homeworks-authorize-url")).toBeTruthy();
    expect(screen.getByTestId("homeworks-token-url")).toBeTruthy();
    expect(screen.getByTestId("homeworks-redirect-uri")).toBeTruthy();
    expect(screen.getByTestId("homeworks-scopes")).toBeTruthy();
    expect(screen.getByTestId("homeworks-mcp-url")).toBeTruthy();
    expect(screen.getByTestId("homeworks-save")).toBeTruthy();
    expect(screen.getByTestId("homeworks-connect")).toBeTruthy();
  });

  it("hides the smoke-test card when disconnected", async () => {
    mockGet.mockResolvedValue(DISCONNECTED_STATE);
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-integration-page")).toBeTruthy();
    });
    expect(screen.queryByTestId("homeworks-card-smoketest")).toBeNull();
    expect(screen.queryByTestId("homeworks-smoketest")).toBeNull();
  });

  it("shows the smoke-test card when connected", async () => {
    mockGet.mockResolvedValue(CONNECTED_STATE);
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-card-smoketest")).toBeTruthy();
    });
    expect(screen.getByTestId("homeworks-smoketest")).toBeTruthy();
    expect(screen.getByTestId("homeworks-disconnect")).toBeTruthy();
  });

  it("pre-fills the form from the GET response", async () => {
    mockGet.mockResolvedValue(CONNECTED_STATE);
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-client-id").value).toBe("cli-42");
    });
    expect(screen.getByTestId("homeworks-authorize-url").value)
      .toBe("https://a/oauth/authorize");
    expect(screen.getByTestId("homeworks-token-url").value)
      .toBe("https://a/oauth/token");
    expect(screen.getByTestId("homeworks-scopes").value)
      .toBe("read:customers");
    // Secret is NEVER pre-filled from the server.
    expect(screen.getByTestId("homeworks-client-secret").value).toBe("");
  });

  it("PUTs a well-formed payload when Save is clicked", async () => {
    mockGet.mockResolvedValue(DISCONNECTED_STATE);
    mockPut.mockResolvedValue(DISCONNECTED_STATE);
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-client-id")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("homeworks-client-id"),
      { target: { value: "  cli-new  " } });
    fireEvent.change(screen.getByTestId("homeworks-client-secret"),
      { target: { value: "top-secret" } });
    fireEvent.change(screen.getByTestId("homeworks-authorize-url"),
      { target: { value: "https://a/x" } });
    fireEvent.change(screen.getByTestId("homeworks-token-url"),
      { target: { value: "https://a/t" } });
    fireEvent.change(screen.getByTestId("homeworks-scopes"),
      { target: { value: "read:customers\n\nread:jobs" } });
    fireEvent.click(screen.getByTestId("homeworks-save"));
    await waitFor(() => expect(mockPut).toHaveBeenCalledTimes(1));
    const [path, body] = mockPut.mock.calls[0];
    expect(path).toBe("/admin/integrations/homeworks");
    expect(body.client_id).toBe("cli-new");        // trimmed
    expect(body.client_secret).toBe("top-secret"); // passed through
    expect(body.authorize_url).toBe("https://a/x");
    expect(body.token_url).toBe("https://a/t");
    expect(body.scopes).toEqual(["read:customers", "read:jobs"]);
    expect(body.mcp_server_url).toBe("https://www.home.works/connect/mcp");
  });

  it("passes empty-string client_secret when the field is untouched", async () => {
    mockGet.mockResolvedValue(CONNECTED_STATE);
    mockPut.mockResolvedValue(CONNECTED_STATE);
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-client-id").value).toBe("cli-42");
    });
    // Don't touch the secret field.
    fireEvent.click(screen.getByTestId("homeworks-save"));
    await waitFor(() => expect(mockPut).toHaveBeenCalledTimes(1));
    const [, body] = mockPut.mock.calls[0];
    expect(body.client_secret).toBe("");
  });

  it("Connect opens the authorize URL in a new tab", async () => {
    mockGet.mockResolvedValue(DISCONNECTED_STATE);
    mockPost.mockResolvedValueOnce({
      authorize_url: "https://a/oauth/authorize?client_id=x&state=y",
      state: "y", redirect_uri: "https://cb/cb",
    });
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-connect")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("homeworks-connect"));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    expect(mockPost.mock.calls[0][0])
      .toBe("/admin/integrations/homeworks/connect");
    await waitFor(() => expect(_openSpy).toHaveBeenCalledTimes(1));
    expect(_openSpy.mock.calls[0][0])
      .toBe("https://a/oauth/authorize?client_id=x&state=y");
    expect(_openSpy.mock.calls[0][1]).toBe("_blank");
  });

  it("renders tools + sample customer JSON after smoke test", async () => {
    mockGet.mockResolvedValue(CONNECTED_STATE);
    mockPost.mockResolvedValueOnce({
      connected: true,
      tools: [{ name: "list_customers", description: "Fetch customers" }],
      sample_customer: { id: "c-1", name: "Ada Lovelace" },
      hint: "used list_customers(limit=1)",
      used_tool: "list_customers",
    });
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-smoketest")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("homeworks-smoketest"));
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-smoketest-tools")).toBeTruthy();
    });
    const toolsPre = screen.getByTestId("homeworks-smoketest-tools");
    expect(toolsPre.textContent).toContain("list_customers");
    const samplePre = screen.getByTestId("homeworks-smoketest-sample");
    expect(samplePre.textContent).toContain("Ada Lovelace");
    expect(screen.getByTestId("homeworks-smoketest-hint").textContent)
      .toBe("used list_customers(limit=1)");
  });

  it("shows last_error banner when connection_status is error", async () => {
    mockGet.mockResolvedValue({
      ...DISCONNECTED_STATE,
      connection_status: "error",
      last_error: "token_http_401:unauthorized",
    });
    render(<HomeworksIntegrationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-last-error")).toBeTruthy();
    });
    expect(screen.getByTestId("homeworks-last-error").textContent)
      .toContain("token_http_401:unauthorized");
    expect(screen.getByTestId("homeworks-status-error")).toBeTruthy();
  });
});
