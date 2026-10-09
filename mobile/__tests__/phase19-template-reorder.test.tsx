/**
 * Phase 19 · Feature 3 — template field reorder runtime on the mobile
 * ServiceReport (web parity d60c85630 · Phase 14A).
 *
 *   * template present → sections render in ``fieldsOrdered`` sequence
 *   * isEmpty → hardcoded source order (zero regression)
 *   * TemplateOrderedSections contract: skip-missing, append-unmentioned,
 *     head/tail passthroughs, mid-run passthrough anchored to predecessor
 */
import React from "react";
import { View } from "react-native";
import { render } from "@testing-library/react-native";

let mockTpl: any = null; // null → isEmpty
jest.mock("@/src/hooks/useFormTemplateRuntime", () => ({
  useFormTemplateRuntime: () => (mockTpl
    ? { fieldsById: mockTpl, fieldsOrdered: Object.values(mockTpl).sort((a: any, b: any) => a.order - b.order), isLoading: false, error: null, isEmpty: false, version: 1 }
    : { fieldsById: {}, fieldsOrdered: [], isLoading: false, error: "http_403", isEmpty: true, version: null }),
}));
const mockReport = { template: "pool", submitted_at: null, photos: [], job: { id: "j1" }, readings: [], chemicals_added: [], checklist: [], notes: "" };
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "j1" }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []),
}));
jest.mock("@/src/api", () => ({
  api: { get: jest.fn(async () => mockReport), post: jest.fn(async () => ({})), patch: jest.fn(async () => ({})) },
  api_base: () => "http://test/api", getAuthToken: async () => "tok",
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: "technician", name: "T", email: "t@x" } }) }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }), SafeAreaView: ({ children }: any) => children }));
jest.mock("expo-image", () => ({ Image: "Image" }));
jest.mock("expo-image-picker", () => ({}));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/services/readCache", () => ({ writeCache: async () => {}, readCache: async () => null }));
jest.mock("@/src/services/sync/photoWorker", () => ({ capturePhoto: jest.fn(), getPhotosForEntity: async () => [] }));

import ServiceReport from "@/app/(app)/service-report/[id]";
import { TemplateFieldProvider, TemplateOrderedSections } from "@/src/components/form-renderer/TemplateFieldContext";

const SECTION_IDS = new Set([
  "svc-report-photos", "svc-report-readings", "svc-report-algae",
  "svc-report-chems", "svc-report-checklist", "svc-report-notes",
]);

function testIdsInOrder(node: any, filter: (id: string) => boolean, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => testIdsInOrder(n, filter, out)); return out; }
  const id = node.props?.testID;
  if (typeof id === "string" && filter(id) && !out.includes(id)) out.push(id);
  testIdsInOrder(node.children, filter, out);
  return out;
}

const F = (field_id: string, order: number) => ({ field_id, order, style: {} });

beforeEach(() => { mockTpl = null; });

describe("ServiceReport · template field order", () => {
  it("isEmpty → hardcoded source order", async () => {
    const r = render(<ServiceReport />);
    await r.findByTestId("svc-report-photos");
    expect(testIdsInOrder(r.toJSON(), (id) => SECTION_IDS.has(id))).toEqual([
      "svc-report-photos", "svc-report-readings", "svc-report-algae",
      "svc-report-chems", "svc-report-checklist", "svc-report-notes",
    ]);
  });

  it("template present → fieldsOrdered sequence (algae rides with readings)", async () => {
    mockTpl = {
      notes: F("notes", 1),
      checklist_section: F("checklist_section", 2),
      chemistry_readings: F("chemistry_readings", 3),
      photos: F("photos", 4),
      chemicals_added_section: F("chemicals_added_section", 5),
    };
    const r = render(<ServiceReport />);
    await r.findByTestId("svc-report-photos");
    expect(testIdsInOrder(r.toJSON(), (id) => SECTION_IDS.has(id))).toEqual([
      "svc-report-notes", "svc-report-checklist", "svc-report-readings",
      "svc-report-algae", "svc-report-photos", "svc-report-chems",
    ]);
  });
});

describe("TemplateOrderedSections contract", () => {
  const Sec = ({ testID }: any) => <View testID={testID} />;
  const tree = (
    <TemplateOrderedSections>
      <Sec testID="head" />
      <Sec testID="a" templateFieldId="a" />
      <Sec testID="mid" />
      <Sec testID="b" templateFieldId="b" />
      {false}
      {null}
      <Sec testID="c" templateFieldId="c" />
      <Sec testID="tail" />
    </TemplateOrderedSections>
  );
  const ids = (ui: any) => testIdsInOrder(render(ui).toJSON(), () => true);

  it("no provider → source order", () => {
    expect(ids(tree)).toEqual(["head", "a", "mid", "b", "c", "tail"]);
  });

  it("reorders, skips missing template ids, appends unmentioned, keeps head/tail", () => {
    const map = { c: F("c", 1), zzz: F("zzz", 2), a: F("a", 3) };
    expect(ids(<TemplateFieldProvider fieldsById={map as any}>{tree}</TemplateFieldProvider>))
      .toEqual(["head", "c", "a", "mid", "b", "tail"]);
  });
});
