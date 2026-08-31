/**
 * Phase F2 · Feb-2026 — TemplateEditorModal validation + submit tests.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}));

import { TemplateEditorModal } from "@/pages/admin/AdminChargeTemplatesPage";

const noop = () => {};

beforeEach(() => vi.clearAllMocks());

describe("TemplateEditorModal · validation + submit", () => {
  it("blocks submit when name is empty", () => {
    const onSubmit = vi.fn();
    render(<TemplateEditorModal open mode="create"
                                initial={null}
                                onClose={noop} onSubmit={onSubmit}
                                busy={false} />);
    fireEvent.click(screen.getByTestId("charge-template-save"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByTestId("charge-template-editor-error").textContent)
      .toMatch(/name is required/i);
  });

  it("blocks submit when a row has no name", () => {
    const onSubmit = vi.fn();
    render(<TemplateEditorModal open mode="create"
                                initial={null}
                                onClose={noop} onSubmit={onSubmit}
                                busy={false} />);
    fireEvent.change(screen.getByTestId("charge-template-name"), {
      target: { value: "Test bundle" },
    });
    // First row unit_price valid but name empty.
    fireEvent.change(screen.getByTestId("charge-template-row-0-price"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByTestId("charge-template-save"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByTestId("charge-template-editor-error").textContent)
      .toMatch(/needs a name/i);
  });

  it("submits a valid create payload", () => {
    const onSubmit = vi.fn();
    render(<TemplateEditorModal open mode="create"
                                initial={null}
                                onClose={noop} onSubmit={onSubmit}
                                busy={false} />);
    fireEvent.change(screen.getByTestId("charge-template-name"), {
      target: { value: "Chlorine Shock Combo" },
    });
    fireEvent.change(screen.getByTestId("charge-template-category"), {
      target: { value: "chemicals" },
    });
    fireEvent.change(screen.getByTestId("charge-template-row-0-name"), {
      target: { value: "Cal-Hypo" },
    });
    fireEvent.change(screen.getByTestId("charge-template-row-0-price"), {
      target: { value: "12.5" },
    });
    fireEvent.change(screen.getByTestId("charge-template-row-0-qty"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByTestId("charge-template-save"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.name).toBe("Chlorine Shock Combo");
    expect(payload.category).toBe("chemicals");
    expect(payload.line_items).toHaveLength(1);
    expect(payload.line_items[0]).toMatchObject({
      name: "Cal-Hypo", unit_price: 12.5, quantity: 2,
    });
  });

  it("preloads fields when editing an existing template", async () => {
    const onSubmit = vi.fn();
    const initial = {
      id: "tpl-9", name: "Existing", description: "Existing desc",
      category: "maintenance",
      line_items: [
        { name: "Item A", unit_price: 5, quantity: 3, category: "labor" },
        { name: "Item B", unit_price: 10, quantity: 1 },
      ],
    };
    render(<TemplateEditorModal open mode="edit"
                                initial={initial}
                                onClose={noop} onSubmit={onSubmit}
                                busy={false} />);
    await waitFor(() =>
      expect(screen.getByTestId("charge-template-name").value).toBe("Existing"),
    );
    expect(screen.getByTestId("charge-template-category").value)
      .toBe("maintenance");
    expect(screen.getByTestId("charge-template-row-0-name").value).toBe("Item A");
    expect(screen.getByTestId("charge-template-row-1-name").value).toBe("Item B");
    fireEvent.click(screen.getByTestId("charge-template-save"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].line_items).toHaveLength(2);
  });

  it("adds and removes line-item rows", () => {
    render(<TemplateEditorModal open mode="create"
                                initial={null}
                                onClose={noop} onSubmit={noop}
                                busy={false} />);
    expect(screen.getByTestId("charge-template-row-0")).toBeTruthy();
    fireEvent.click(screen.getByTestId("charge-template-add-row"));
    expect(screen.getByTestId("charge-template-row-1")).toBeTruthy();
    fireEvent.click(screen.getByTestId("charge-template-row-1-remove"));
    expect(screen.queryByTestId("charge-template-row-1")).toBeNull();
  });
});
