/**
 * Feb-2026 · P36-followup — Mobile CustomerTagsSection uses
 * PATCH /customers/{cid}/tags full-replace payload instead of the
 * missing POST /customer-tags/{id}/attach|detach endpoints.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockApiGet = jest.fn();
const mockApiPatch = jest.fn();
const mockApiPost = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    patch: (...a: any[]) => mockApiPatch(...a),
    post: (...a: any[]) => mockApiPost(...a),
  },
}));

jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

jest.mock("@/src/theme", () => ({
  colors: { onSurface: "#fff", muted: "#888", surface: "#111",
             surfaceSecondary: "#222", surfaceTertiary: "#333",
             border: "#444", divider: "#333", onSurfaceSecondary: "#aaa",
             brandPrimary: "#0af" },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, md: 14, lg: 16, xl: 20 },
  // Mirrors src/theme.ts:74 — AppTextInput reads it at module load.
  inputColors: { bg: "#FFFFFF", text: "#000080", placeholder: "rgba(0,0,128,0.55)" },
}));


beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPatch.mockReset();
  mockApiPost.mockReset();
  mockApiPatch.mockResolvedValue({ ok: true, tags: [] });
});


describe("Mobile CustomerTagsSection · P36-followup PATCH refactor", () => {
  it("removing a tag calls PATCH /customers/{cid}/tags with remaining names", async () => {
    const CustomerTagsSection = require(
      "../src/components/customers/CustomerTagsSection").default;
    const attached = [
      { id: "t-1", name: "VIP", color: "#DBEAFE" },
      { id: "t-2", name: "Waitlist", color: "#DBEAFE" },
    ];
    const onChange = jest.fn();
    const utils = render(
      <CustomerTagsSection customerId="cust-1" value={attached} onChange={onChange} />);

    const removeBtn = utils.getByTestId("customer-tag-chip-remove-t-1");
    await act(async () => { fireEvent.press(removeBtn); });

    await waitFor(() => expect(mockApiPatch).toHaveBeenCalled());
    const [path, body] = mockApiPatch.mock.calls[0];
    expect(path).toBe("/customers/cust-1/tags");
    expect(body).toEqual({ tags: ["Waitlist"] });
    expect(onChange).toHaveBeenCalledWith([
      { id: "t-2", name: "Waitlist", color: "#DBEAFE" },
    ]);
  });

  it("adding an existing tag calls PATCH with appended names", async () => {
    mockApiGet.mockResolvedValue({ items: [
      { id: "t-3", name: "New Tag", color: "#DBEAFE" },
    ]});
    const CustomerTagsSection = require(
      "../src/components/customers/CustomerTagsSection").default;
    const attached = [{ id: "t-1", name: "VIP", color: "#DBEAFE" }];
    const onChange = jest.fn();
    const utils = render(
      <CustomerTagsSection customerId="cust-1" value={attached} onChange={onChange} />);

    // Open the picker → fetches catalog → tap the tag.
    await act(async () => {
      fireEvent.press(utils.getByTestId("customer-tags-open-picker"));
    });
    await waitFor(() =>
      expect(utils.getByTestId("customer-tags-picker-item-t-3")).toBeTruthy());
    await act(async () => {
      fireEvent.press(utils.getByTestId("customer-tags-picker-item-t-3"));
    });

    await waitFor(() => expect(mockApiPatch).toHaveBeenCalled());
    const [path, body] = mockApiPatch.mock.calls[0];
    expect(path).toBe("/customers/cust-1/tags");
    // Order matters: existing tag first, then the newly-attached one.
    expect(body).toEqual({ tags: ["VIP", "New Tag"] });
  });

  it("creating a new tag via picker relies on PATCH auto-persist (no POST /customer-tags)", async () => {
    mockApiGet.mockResolvedValue({ items: [] });
    const CustomerTagsSection = require(
      "../src/components/customers/CustomerTagsSection").default;
    const onChange = jest.fn();
    const utils = render(
      <CustomerTagsSection customerId="cust-1" value={[]} onChange={onChange} />);

    await act(async () => {
      fireEvent.press(utils.getByTestId("customer-tags-open-picker"));
    });
    await waitFor(() =>
      expect(utils.getByTestId("customer-tags-picker-search")).toBeTruthy());
    // Type a brand-new tag name.
    await act(async () => {
      fireEvent.changeText(
        utils.getByTestId("customer-tags-picker-search"), "Freshly Made");
    });
    await waitFor(() =>
      expect(utils.getByTestId("customer-tags-picker-create")).toBeTruthy());
    await act(async () => {
      fireEvent.press(utils.getByTestId("customer-tags-picker-create"));
    });

    // PATCH called with the new name; NO separate POST /customer-tags.
    await waitFor(() => expect(mockApiPatch).toHaveBeenCalled());
    const [path, body] = mockApiPatch.mock.calls[0];
    expect(path).toBe("/customers/cust-1/tags");
    expect(body).toEqual({ tags: ["Freshly Made"] });
    // Regression pin: no POST /customer-tags (backend PATCH auto-persists).
    const postCatalog = mockApiPost.mock.calls.filter(
      (c) => c[0] === "/customer-tags");
    expect(postCatalog.length).toBe(0);
  });

  it("regression pin: no /attach or /detach paths are called anywhere", async () => {
    mockApiGet.mockResolvedValue({ items: [
      { id: "t-3", name: "Extra", color: "#DBEAFE" },
    ]});
    const CustomerTagsSection = require(
      "../src/components/customers/CustomerTagsSection").default;
    const attached = [{ id: "t-1", name: "VIP", color: "#DBEAFE" }];
    const utils = render(
      <CustomerTagsSection customerId="cust-1" value={attached} onChange={() => {}} />);

    // Attach: pick existing.
    await act(async () => {
      fireEvent.press(utils.getByTestId("customer-tags-open-picker"));
    });
    await waitFor(() =>
      expect(utils.getByTestId("customer-tags-picker-item-t-3")).toBeTruthy());
    await act(async () => {
      fireEvent.press(utils.getByTestId("customer-tags-picker-item-t-3"));
    });
    // Detach existing tag.
    await act(async () => {
      fireEvent.press(utils.getByTestId("customer-tag-chip-remove-t-1"));
    });

    // Neither POST nor PATCH should touch /attach or /detach paths.
    const allCallPaths = [
      ...mockApiPost.mock.calls.map((c) => c[0]),
      ...mockApiPatch.mock.calls.map((c) => c[0]),
      ...mockApiGet.mock.calls.map((c) => c[0]),
    ];
    for (const p of allCallPaths) {
      expect(String(p)).not.toMatch(/\/attach\b/);
      expect(String(p)).not.toMatch(/\/detach\b/);
    }
  });
});
