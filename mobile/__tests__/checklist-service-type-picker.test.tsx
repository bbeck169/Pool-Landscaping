/**
 * Feb-2026 · Checklist reclassifier — mobile PoolChecklistForm parity.
 *
 * Mirrors ``frontend/src/test/pool-checklist-service-type-picker.test.jsx``:
 * asserts the Chemical Readings empty-state picker renders when the
 * report's ``template`` is ``"generic"`` and ``readingFields`` is
 * empty, and is hidden in the tenant-misconfig case
 * (``template="pool"`` + empty fields).
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

jest.setTimeout(15000);

const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: (...a: any[]) => mockApiPost(...a),
    put: (...a: any[]) => jest.fn()(...a),
    patch: (...a: any[]) => jest.fn()(...a),
  },
  api_base: () => "https://example.test/api",
  getAuthToken: async () => "tok",
}));

jest.mock("react-native-draggable-flatlist", () => {
  const { View } = require("react-native");
  const DraggableFlatList = ({ data, renderItem }: any) => (
    <View>{(data || []).map((item: any, index: number) =>
      renderItem({ item, drag: () => {}, isActive: false, getIndex: () => index })
    )}</View>
  );
  return {
    __esModule: true,
    default: DraggableFlatList,
    ScaleDecorator: ({ children }: any) => children,
  };
});

jest.mock("expo-image-picker", () => ({
  launchImageLibraryAsync: jest.fn(async () => ({ canceled: true })),
  launchCameraAsync: jest.fn(async () => ({ canceled: true })),
  requestMediaLibraryPermissionsAsync: jest.fn(async () => ({ granted: true })),
  requestCameraPermissionsAsync: jest.fn(async () => ({ granted: true })),
  MediaTypeOptions: { Images: "Images" },
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
  SafeAreaProvider: ({ children }: any) => children,
  SafeAreaView: ({ children }: any) => children,
}));

import PoolChecklistForm from "@/src/components/checklist/PoolChecklistForm";

const baseProps = {
  jobId: "job-1",
  customerId: "cust-1",
  locked: false,
  readings: [],
  chemicalsAdded: [],
  chemicalsCatalog: [],
  chemicalUnits: ["gal", "lbs", "oz", "tabs"],
  checklistItems: [],
  notes: "",
  observations: {},
  onChange: jest.fn(),
};

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiGet.mockResolvedValue({ readings: {}, recent_readings: {} });
  mockApiPost.mockReset();
});

describe("mobile PoolChecklistForm · Chemical Readings reclassify picker", () => {
  it("renders the picker when readingFields=[] AND template='generic'", async () => {
    const onReclassify = jest.fn(async () => {});
    const tree = render(
      <PoolChecklistForm
        {...(baseProps as any)}
        readingFields={[]}
        template="generic"
        canEditServiceType={true}
        onReclassify={onReclassify}
      />,
    );
    await waitFor(() => {
      expect(tree.getByTestId("pool-service-type-picker-block")).toBeTruthy();
    });
    expect(tree.getByTestId("pool-service-type-picker")).toBeTruthy();
    expect(tree.getByTestId("pool-service-type-set-pool-service")).toBeTruthy();
    expect(tree.getByTestId("pool-service-type-set-landscape-service")).toBeTruthy();
    expect(tree.getByTestId("pool-service-type-set-other")).toBeTruthy();
  });

  it("HIDES the picker when template='pool' (tenant misconfig)", async () => {
    const tree = render(
      <PoolChecklistForm
        {...(baseProps as any)}
        readingFields={[]}
        template="pool"
        canEditServiceType={true}
        onReclassify={jest.fn()}
      />,
    );
    // Give the mount effect time to run.
    await waitFor(() => expect(tree.getByTestId("pool-checklist-form")).toBeTruthy());
    expect(tree.queryByTestId("pool-service-type-picker-block")).toBeNull();
  });

  it("shows the read-only hint when canEditServiceType=false", async () => {
    const tree = render(
      <PoolChecklistForm
        {...(baseProps as any)}
        readingFields={[]}
        template="generic"
        canEditServiceType={false}
        onReclassify={jest.fn()}
      />,
    );
    await waitFor(() => {
      expect(tree.getByTestId("pool-service-type-readonly-hint")).toBeTruthy();
    });
    expect(tree.queryByTestId("pool-service-type-picker")).toBeNull();
  });

  it("invokes onReclassify('Pool Service') when Pool Service is tapped", async () => {
    const onReclassify = jest.fn(async () => {});
    const tree = render(
      <PoolChecklistForm
        {...(baseProps as any)}
        readingFields={[]}
        template="generic"
        canEditServiceType={true}
        onReclassify={onReclassify}
      />,
    );
    await waitFor(() => {
      expect(tree.getByTestId("pool-service-type-set-pool-service")).toBeTruthy();
    });
    fireEvent.press(tree.getByTestId("pool-service-type-set-pool-service"));
    await waitFor(() => expect(onReclassify).toHaveBeenCalledTimes(1));
    expect(onReclassify).toHaveBeenCalledWith("Pool Service");
  });
});
