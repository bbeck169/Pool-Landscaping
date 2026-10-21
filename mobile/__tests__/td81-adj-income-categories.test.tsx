/**
 * TD-81-adj b2 · app/income-categories.tsx in-place fix.
 * GET returns {items:[{id,name}], total}; POST returns the created doc (so
 * we reload); Remove → Archive via POST /income-categories/{id}/archive.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockDel = jest.fn();
let mockConfirm: any = null;

jest.mock("@/src/api", () => ({
  api: { get: (u: string) => mockGet(u), post: (u: string, b: any) => mockPost(u, b), del: (u: string) => mockDel(u) },
}));
jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(() => { cb(); }, []); },
}));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/components/ui", () => ({ Loading: () => null }));
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: (o: any) => { mockConfirm = o; } }));
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return { __esModule: true, default: (p: any) => <TextInput {...p} /> };
});

import IncomeCategories from "@/app/income-categories";

let rows: { id: string; name: string }[] = [];

beforeEach(() => {
  rows = [{ id: "c1", name: "Pool" }, { id: "c2", name: "Landscaping" }];
  mockConfirm = null;
  mockDel.mockReset();
  mockGet.mockReset().mockImplementation(async (u: string) => {
    if (u === "/income-categories") return { items: rows.map((r) => ({ ...r, is_archived: false })), total: rows.length };
    throw new Error(`unexpected GET ${u}`);
  });
  mockPost.mockReset().mockImplementation(async (u: string, b: any) => {
    if (u === "/income-categories") { const doc = { id: "c9", name: b.name }; rows = [...rows, doc]; return doc; }
    const m = u.match(/^\/income-categories\/([^/]+)\/archive$/);
    if (m) { rows = rows.filter((r) => r.id !== m[1]); return { ok: true, id: m[1], is_archived: true }; }
    throw new Error(`unexpected POST ${u}`);
  });
});

it("C1 · lists category names from {items, total}", async () => {
  const q = render(<IncomeCategories />);
  await waitFor(() => expect(q.getByTestId("cat-Pool")).toBeTruthy());
  expect(q.getByTestId("cat-Landscaping")).toBeTruthy();
  expect(q.getAllByText("Archive")).toHaveLength(2);
});

it("C2 · Add POSTs the name, then reloads the list (POST returns a doc, not a list)", async () => {
  const q = render(<IncomeCategories />);
  await waitFor(() => expect(q.getByTestId("cat-Pool")).toBeTruthy());
  fireEvent.changeText(q.getByTestId("cat-input"), "  Repairs ");
  await act(async () => { fireEvent.press(q.getByTestId("cat-add")); });
  expect(mockPost).toHaveBeenCalledWith("/income-categories", { name: "Repairs" });
  await waitFor(() => expect(q.getByTestId("cat-Repairs")).toBeTruthy());
  expect(mockGet).toHaveBeenCalledTimes(2);
  expect(q.getByTestId("cat-input").props.value).toBe("");
});

it("C3 · Archive confirms, POSTs /income-categories/{id}/archive (never DELETE), reloads", async () => {
  const q = render(<IncomeCategories />);
  await waitFor(() => expect(q.getByTestId("cat-archive-Pool")).toBeTruthy());
  fireEvent.press(q.getByTestId("cat-archive-Pool"));
  expect(mockConfirm).toMatchObject({ title: "Archive category", confirmLabel: "Archive" });
  await act(async () => { await mockConfirm.onConfirm(); });
  expect(mockPost).toHaveBeenCalledWith("/income-categories/c1/archive", {});
  expect(mockDel).not.toHaveBeenCalled();
  await waitFor(() => expect(q.queryByTestId("cat-Pool")).toBeNull());
  expect(q.getByTestId("cat-Landscaping")).toBeTruthy();
});
