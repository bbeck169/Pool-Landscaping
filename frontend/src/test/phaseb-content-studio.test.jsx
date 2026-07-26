/**
 * Feb-2026 · Phase B · Marketing Content Studio — vitest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock, apiPostMock, apiDelMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(), apiPostMock: vi.fn(), apiDelMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: apiGetMock, post: apiPostMock, del: apiDelMock },
  api_base: () => "http://test.example/api",
}));

vi.mock("@/components/layout/SafeScrollContainer", () => ({
  __esModule: true,
  default: ({ children, ...rest }) => <div {...rest}>{children}</div>,
}));


beforeEach(() => {
  apiGetMock.mockReset(); apiPostMock.mockReset(); apiDelMock.mockReset();
});
afterEach(() => { vi.restoreAllMocks(); });


describe("Phase B · Content Studio", () => {
  it("renders the prompt card + generate CTA", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve({ connected: true });
      if (path.startsWith("/media/library"))
        return Promise.resolve({ items: [], total: 0,
                                     quota: { used: 3, limit: 100 } });
      return Promise.resolve({});
    });
    const { default: Page } = await import(
      "@/pages/marketing/ContentStudioPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    expect(await screen.findByTestId("content-studio-page"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("content-studio-generate-btn"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("content-studio-quota"))
      .toHaveTextContent("3/100");
    // No degraded banner when connected.
    expect(screen.queryByTestId("content-studio-degraded-banner")).toBeNull();
    expect(screen.queryByTestId("content-studio-library-empty")).toBeInTheDocument();
  });

  it("shows degraded banner when Supercool is not connected", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve({ connected: false });
      if (path.startsWith("/media/library"))
        return Promise.resolve({ items: [], total: 0 });
      return Promise.resolve({});
    });
    const { default: Page } = await import(
      "@/pages/marketing/ContentStudioPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    expect(await screen.findByTestId("content-studio-degraded-banner"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("content-studio-connect-link"))
      .toHaveAttribute("href", "/settings/integrations/supercool");
  });

  it("POSTs /media/image/generate on click + shows the result", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve({ connected: true });
      if (path.startsWith("/media/library"))
        return Promise.resolve({ items: [], total: 0 });
      return Promise.resolve({});
    });
    apiPostMock.mockResolvedValue({
      image_id: "img-1", url: "/uploads/generated/img-1.png",
      provider: "supercool", tool_used: "image_generate",
      prompt: "aqua pool at sunset with palms", aspect_ratio: "1:1",
      quota: { used: 1, limit: 100 },
    });

    const { default: Page } = await import(
      "@/pages/marketing/ContentStudioPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("content-studio-page");

    const textarea = screen.getByTestId("content-studio-prompt-input");
    fireEvent.change(textarea,
      { target: { value: "aqua pool at sunset with palms" } });
    fireEvent.click(screen.getByTestId("content-studio-generate-btn"));

    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith(
        "/media/image/generate",
        expect.objectContaining({
          prompt: "aqua pool at sunset with palms",
          aspect_ratio: "1:1", surface: "marketing",
        }),
      ));
    const img = await screen.findByTestId("content-studio-result-image");
    expect(img).toHaveAttribute("src",
      "http://test.example/uploads/generated/img-1.png");
  });

  it("switches to /media/image/edit when a reference URL is provided", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve({ connected: true });
      if (path.startsWith("/media/library"))
        return Promise.resolve({ items: [], total: 0 });
      return Promise.resolve({});
    });
    apiPostMock.mockResolvedValue({
      image_id: "img-2", url: "/uploads/generated/img-2.png",
      provider: "supercool", tool_used: "image_generate",
      prompt: "restored pool", quota: { used: 1, limit: 100 },
    });

    const { default: Page } = await import(
      "@/pages/marketing/ContentStudioPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("content-studio-page");

    fireEvent.change(screen.getByTestId("content-studio-prompt-input"),
      { target: { value: "restored pool" } });
    fireEvent.change(screen.getByTestId("content-studio-refurl-input"),
      { target: { value: "https://cust.example/before.jpg" } });
    fireEvent.click(screen.getByTestId("content-studio-generate-btn"));

    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith(
        "/media/image/edit",
        expect.objectContaining({
          prompt: "restored pool",
          source_image_url: "https://cust.example/before.jpg",
        }),
      ));
  });

  it("shows a friendly toast on daily_limit_reached", async () => {
    const { toast } = await import("sonner");
    apiGetMock.mockImplementation((path) => {
      if (path === "/integrations/supercool/status")
        return Promise.resolve({ connected: true });
      if (path.startsWith("/media/library"))
        return Promise.resolve({ items: [], total: 0 });
      return Promise.resolve({});
    });
    apiPostMock.mockRejectedValue(new Error("daily_limit_reached"));

    const { default: Page } = await import(
      "@/pages/marketing/ContentStudioPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("content-studio-page");
    fireEvent.change(screen.getByTestId("content-studio-prompt-input"),
      { target: { value: "any prompt long enough" } });
    fireEvent.click(screen.getByTestId("content-studio-generate-btn"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/Daily image-generation limit/i)));
  });
});
