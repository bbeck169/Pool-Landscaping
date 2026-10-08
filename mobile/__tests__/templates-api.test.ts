/**
 * Templates Library — Phase 3 (Mobile) · API client parity with web
 * `frontend/src/api/templates.js` + native PDF download (File + Sharing).
 */
const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPatch = jest.fn();
const mockDel = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    post: (...a: any[]) => mockPost(...a),
    patch: (...a: any[]) => mockPatch(...a),
    del: (...a: any[]) => mockDel(...a),
  },
  api_base: () => "https://x.test/api",
  getAuthToken: async () => "tok123",
}));
const mockExpoFetch = jest.fn();
jest.mock("expo/fetch", () => ({ fetch: (...a: any[]) => mockExpoFetch(...a) }));
const mockWrite = jest.fn();
const mockCreate = jest.fn();
jest.mock("expo-file-system", () => ({
  Paths: { cache: "file:///cache" },
  File: jest.fn().mockImplementation((_dir: string, name: string) => ({
    uri: `file:///cache/${name}`, write: mockWrite, create: mockCreate,
  })),
}));
const mockShare = jest.fn();
jest.mock("expo-sharing", () => ({ isAvailableAsync: async () => true, shareAsync: (...a: any[]) => mockShare(...a) }));

import * as T from "@/src/api/templates";

beforeEach(() => jest.clearAllMocks());

it("hits the same endpoints as the web client", async () => {
  T.listDefinitions(); T.listDefinitions("documents"); T.getDefinition("a b");
  T.listInstances({ mine: true }); T.getInstance("i1");
  T.createInstance({ template_code: "c" }); T.updateInstance("i1", { title: "t" });
  T.finalizeInstance("i1"); T.duplicateInstance("i1"); T.deleteInstance("i1");
  expect(mockGet.mock.calls.map((c) => c[0])).toEqual([
    "/templates/definitions", "/templates/definitions?category=documents", "/templates/definitions/a%20b",
    "/templates/instances?mine=true", "/templates/instances/i1",
  ]);
  expect(mockPost.mock.calls).toEqual([
    ["/templates/instances", { template_code: "c", title: undefined, values: {} }],
    ["/templates/instances/i1/finalize"],
    ["/templates/instances/i1/duplicate"],
  ]);
  expect(mockPatch).toHaveBeenCalledWith("/templates/instances/i1", { title: "t" });
  expect(mockDel).toHaveBeenCalledWith("/templates/instances/i1");
});

it("exposes the 5 web categories with full labels", () => {
  expect(T.TEMPLATE_CATEGORIES.map((c) => c.label)).toEqual([
    "All", "Pricing & Money", "Operations & Checklists", "Chemicals & Chemistry", "Documents",
  ]);
  expect(T.CATEGORY_LABEL.chemicals_chemistry).toBe("Chemicals & Chemistry");
});

it("sanitizeFilename produces a safe .pdf name", () => {
  expect(T.sanitizeFilename("Pool Log / Oct?")).toBe("Pool Log _ Oct_.pdf");
  expect(T.sanitizeFilename("x.pdf")).toBe("x.pdf");
  expect(T.sanitizeFilename("")).toBe("template.pdf");
});

it("downloadPdf POSTs with bearer auth, writes to cache, opens share sheet", async () => {
  const bytes = new Uint8Array([37, 80, 68, 70]).buffer; // %PDF
  mockExpoFetch.mockResolvedValue({ ok: true, status: 200, arrayBuffer: async () => bytes });
  const uri = await T.downloadPdf("i1", "My Log");
  expect(mockExpoFetch).toHaveBeenCalledWith("https://x.test/api/templates/instances/i1/pdf", {
    method: "POST", headers: { Authorization: "Bearer tok123" },
  });
  expect(mockWrite).toHaveBeenCalledWith(new Uint8Array([37, 80, 68, 70]));
  expect(uri).toBe("file:///cache/My Log.pdf");
  expect(mockShare).toHaveBeenCalledWith("file:///cache/My Log.pdf", expect.objectContaining({ mimeType: "application/pdf" }));
});

it("downloadPdf surfaces backend detail on error", async () => {
  mockExpoFetch.mockResolvedValue({ ok: false, status: 403, json: async () => ({ detail: "Not allowed" }) });
  await expect(T.downloadPdf("i1")).rejects.toThrow("Not allowed");
  expect(mockShare).not.toHaveBeenCalled();
});
