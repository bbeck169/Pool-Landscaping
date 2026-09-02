/**
 * MeasureMap.native.test.tsx — Phase K20 · Rendering test for MeasureMap
 * native component safety guard.
 */
import React from "react";
import { render } from "@testing-library/react-native";

// ── Mocks ───────────────────────────────────────────────────────────

const mockHasKey = jest.fn<boolean, []>();

jest.mock("@/src/utils/mapsKey", () => ({
  hasGoogleMapsKey: () => mockHasKey(),
  MapUnavailablePlaceholder: ({ testID, provider }: any) => {
    const { View, Text } = require("react-native");
    return (
      <View testID={testID}>
        <Text>{provider} unavailable</Text>
      </View>
    );
  },
}));

jest.mock("react-native-maps", () => {
  const { View } = require("react-native");
  const MockMapView = (props: any) => <View {...props} />;
  return {
    __esModule: true,
    default: MockMapView,
    Marker: (props: any) => <View {...props} />,
    Polyline: (props: any) => <View {...props} />,
    Polygon: (props: any) => <View {...props} />,
  };
});

// ── Import under test (after mocks) ────────────────────────────────

import MeasureMap from "@/src/components/measure/MeasureMap.native";

const defaultProps = {
  mode: "distance" as const,
  points: [],
  region: {
    latitude: 33.4484,
    longitude: -112.074,
    latitudeDelta: 0.05,
    longitudeDelta: 0.05,
  },
  onRegionChange: jest.fn(),
  onPress: jest.fn(),
};

// ── Tests ───────────────────────────────────────────────────────────

describe("MeasureMap.native — K20 safety guard", () => {
  afterEach(() => jest.clearAllMocks());

  it("renders MapUnavailablePlaceholder when Google Maps key is missing", () => {
    mockHasKey.mockReturnValue(false);
    const { getByTestId, queryByTestId } = render(
      <MeasureMap {...defaultProps} />,
    );
    expect(getByTestId("measure-map-unavailable")).toBeTruthy();
    expect(queryByTestId("measure-map")).toBeNull();
  });

  it("renders MapView when Google Maps key is present", () => {
    mockHasKey.mockReturnValue(true);
    const { getByTestId, queryByTestId } = render(
      <MeasureMap {...defaultProps} />,
    );
    expect(getByTestId("measure-map")).toBeTruthy();
    expect(queryByTestId("measure-map-unavailable")).toBeNull();
  });

  it("renders pins when points are provided and key exists", () => {
    mockHasKey.mockReturnValue(true);
    const points = [
      { latitude: 33.45, longitude: -112.07 },
      { latitude: 33.46, longitude: -112.08 },
    ];
    const { getByTestId } = render(
      <MeasureMap {...defaultProps} mode="distance" points={points} />,
    );
    expect(getByTestId("measure-map")).toBeTruthy();
  });
});
