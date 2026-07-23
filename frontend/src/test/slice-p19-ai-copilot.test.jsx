/**
 * Feb-2026 · Item 4 — AI Brain + Copilot vitest.
 * Feb-2026 · Item 2 — Mass Messaging audience_status segmented control.
 * Feb-2026 · Item 3 — Sidebar no longer shows "Recently viewed".
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { apiGetMock, apiPostMock, apiPatchMock, apiDeleteMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(), apiPostMock: vi.fn(),
  apiPatchMock: vi.fn(), apiDeleteMock: vi.fn(),
}));
vi.mock("@/api", () => ({ api: {
  get: apiGetMock, post: apiPostMock,
  patch: apiPatchMock, delete: apiDeleteMock,
}}));

beforeEach(() => {
  apiGetMock.mockReset(); apiPostMock.mockReset();
  apiPatchMock.mockReset(); apiDeleteMock.mockReset();
});

describe("Item 4 — AI Brain settings page", () => {
  it("renders the list + editor and creates a new entry", async () => {
    apiGetMock.mockResolvedValue({ items: [{
      id: "k-1", kind: "company_profile",
      title: "Company Profile",
      content_md: "# hi\n\nWorld",
      is_active: true, tags: [],
    }]});
    apiPostMock.mockResolvedValue({
      id: "k-2", kind: "custom",
      title: "New entry", content_md: "# New entry",
      is_active: true, tags: [],
    });
    const { default: AIBrainPage } = await import("@/pages/settings/AIBrainPage");
    render(<MemoryRouter><AIBrainPage /></MemoryRouter>);
    expect(await screen.findByTestId("ai-brain-page")).toBeInTheDocument();
    expect(await screen.findByTestId("ai-brain-item-k-1")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("ai-brain-new-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/ai/knowledge",
      expect.objectContaining({ kind: "custom" }),
    ));
  });
});

describe("Item 4 — Copilot page", () => {
  it("sends a message and renders the reply", async () => {
    apiPostMock.mockResolvedValue({
      thread_id: "th-1",
      reply: "You have 42 active customers.",
      tool_calls: [{ name: "list_customers", args: { query: "" } }],
    });
    const { default: CopilotPage } = await import("@/pages/admin/CopilotPage");
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    expect(await screen.findByTestId("copilot-page")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("copilot-input"),
                      { target: { value: "How many customers?" } });
    fireEvent.click(screen.getByTestId("copilot-send-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/ai/copilot/message",
      expect.objectContaining({ message: "How many customers?" }),
    ));
    expect(await screen.findByText(/You have 42 active customers/)).toBeInTheDocument();
  });
});
