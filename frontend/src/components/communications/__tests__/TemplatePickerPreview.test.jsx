/**
 * TD-100-sub-template · Feb-2026 — extracted TemplatePickerPreview.
 *
 * Covers:
 *   • Template list renders after fetch.
 *   • Selection → onPick fires with the full template object.
 *   • Deselection → onPick fires with null (Custom-message click).
 *   • Preview-request event → onPreviewRequest called on pick with
 *     template body hydrated.
 *   • Empty state (zero templates).
 *   • Error state (fetch rejects → onError called).
 *   • Channel switch (email ↔ sms) refetches.
 *
 * Testids locked by phase29-composer-template-picker.test.jsx must
 * survive byte-identical: ``cd-send-templates`` (root),
 * ``cd-send-template-custom``, ``cd-send-templates-loading``,
 * ``cd-send-templates-empty``, ``cd-send-template-{id}``.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup }
  from "@testing-library/react";


const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/theme", () => ({
  colors: { border: "#eee", muted: "#888",
             surfaceSecondary: "#f6f6f6", onSurface: "#111" },
}));


import TemplatePickerPreview
  from "@/components/communications/TemplatePickerPreview";


afterEach(() => {
  cleanup();
  getMock.mockReset();
});


function _mount(props) {
  return render(<TemplatePickerPreview {...props} />);
}


describe("TemplatePickerPreview · list fetch + render", () => {
  it("renders template list after fetch (locked testids survive)", async () => {
    getMock.mockResolvedValueOnce({
      templates: [
        { id: "t1", name: "Welcome", subject: "Hi", body: "B1" },
        { id: "t2", name: "Followup", subject: "Hey", body: "B2",
          category: "Marketing" },
      ],
    });
    _mount({ channel: "email", pickedId: "", onPick: vi.fn() });
    // Locked testids present once fetch resolves.
    await waitFor(() => screen.getByTestId("cd-send-template-t1"));
    expect(screen.getByTestId("cd-send-templates")).toBeInTheDocument();
    expect(screen.getByTestId("cd-send-template-custom")).toBeInTheDocument();
    expect(screen.getByTestId("cd-send-template-t2")).toBeInTheDocument();
    expect(screen.getByText("Welcome")).toBeInTheDocument();
    expect(screen.getByText("Marketing")).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith(
      "/marketing/templates?channel=email&active=true");
  });
});


describe("TemplatePickerPreview · selection", () => {
  it("fires onPick with full template object on template click", async () => {
    getMock.mockResolvedValueOnce({
      templates: [{ id: "t1", name: "T1", subject: "S", body: "B" }],
    });
    const onPick = vi.fn();
    _mount({ channel: "email", pickedId: "", onPick });
    await waitFor(() => screen.getByTestId("cd-send-template-t1"));
    fireEvent.click(screen.getByTestId("cd-send-template-t1"));
    expect(onPick).toHaveBeenCalledTimes(1);
    const picked = onPick.mock.calls[0][0];
    expect(picked).toMatchObject({ id: "t1", name: "T1",
                                      subject: "S", body: "B" });
  });

  it("fires onPick with null on Custom-message click", async () => {
    getMock.mockResolvedValueOnce({ templates: [] });
    const onPick = vi.fn();
    _mount({ channel: "email", pickedId: "t1", onPick });
    await waitFor(() =>
      screen.getByTestId("cd-send-templates-empty"));
    fireEvent.click(screen.getByTestId("cd-send-template-custom"));
    expect(onPick).toHaveBeenCalledWith(null);
  });

  it("fires onPreviewRequest alongside onPick on template click", async () => {
    getMock.mockResolvedValueOnce({
      templates: [{ id: "t1", name: "T1", subject: "S", body: "B" }],
    });
    const onPick = vi.fn();
    const onPreviewRequest = vi.fn();
    _mount({ channel: "email", pickedId: "", onPick, onPreviewRequest });
    await waitFor(() => screen.getByTestId("cd-send-template-t1"));
    fireEvent.click(screen.getByTestId("cd-send-template-t1"));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPreviewRequest).toHaveBeenCalledTimes(1);
    expect(onPreviewRequest.mock.calls[0][0]).toMatchObject({
      id: "t1", body: "B",
    });
  });
});


describe("TemplatePickerPreview · empty + error states", () => {
  it("renders empty state when fetch returns zero templates (SMS copy)", async () => {
    getMock.mockResolvedValueOnce({ templates: [] });
    _mount({ channel: "sms", pickedId: "", onPick: vi.fn() });
    const el = await screen.findByTestId("cd-send-templates-empty");
    expect(el.textContent).toContain("SMS");
  });

  it("calls onError when fetch rejects", async () => {
    getMock.mockRejectedValueOnce(new Error("boom"));
    const onError = vi.fn();
    _mount({ channel: "email", pickedId: "", onPick: vi.fn(), onError });
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0]).toBe("boom");
    // Empty state renders when fetch fails (silent fallback).
    expect(screen.getByTestId("cd-send-templates-empty")).toBeInTheDocument();
  });
});


describe("TemplatePickerPreview · channel switch", () => {
  it("refetches with new channel param when channel prop changes", async () => {
    getMock.mockResolvedValueOnce({
      templates: [{ id: "e1", name: "Email T", subject: "", body: "" }],
    });
    const { rerender } = _mount({
      channel: "email", pickedId: "", onPick: vi.fn(),
    });
    await waitFor(() => screen.getByTestId("cd-send-template-e1"));
    expect(getMock).toHaveBeenLastCalledWith(
      "/marketing/templates?channel=email&active=true");
    // Flip to SMS — should refetch.
    getMock.mockResolvedValueOnce({
      templates: [{ id: "s1", name: "SMS T", subject: "", body: "" }],
    });
    rerender(<TemplatePickerPreview channel="sms" pickedId="" onPick={() => {}} />);
    await waitFor(() => screen.getByTestId("cd-send-template-s1"));
    const lastCall = getMock.mock.calls[getMock.mock.calls.length - 1][0];
    expect(lastCall).toBe("/marketing/templates?channel=sms&active=true");
    // Email-side template should no longer be in DOM.
    expect(screen.queryByTestId("cd-send-template-e1")).toBeNull();
  });
});
