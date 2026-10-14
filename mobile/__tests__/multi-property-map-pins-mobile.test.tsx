/**
 * Multi-property map pins — mobile parity for web 723e28204.
 *
 *  A. coord_source → style mapping (property / approximate / normal)
 *  B. approximate fires ONLY on coord_source "customer" + property_id
 *  C. property_label renders in the callout (marker description + info card)
 *     only on the property rung
 */
import React from "react";
import { render, fireEvent, within } from "@testing-library/react-native";

jest.mock("@/src/api", () => ({
  api: { get: jest.fn().mockResolvedValue({}), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));
// Technician → live-tech overlay stays off (no polling noise here).
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: "technician" } }) }));
jest.mock("expo-constants", () => ({
  __esModule: true,
  default: { expoConfig: { android: { config: { googleMaps: { apiKey: "TEST_KEY_STUB" } } } } },
}));
jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  Accuracy: { Balanced: 3 },
}));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock("react-native-maps", () => {
  const RN = require("react-native");
  const R = require("react");
  const MapViewMock = R.forwardRef((props: any, ref: any) => (
    <RN.View ref={ref} testID={props.testID || "map-view"}>{props.children}</RN.View>
  ));
  const MarkerMock = (props: any) => (
    <RN.Pressable testID={props.testID} onPress={props.onPress}>
      <RN.Text>{props.title}</RN.Text>
      {props.description ? (
        <RN.Text testID={`${props.testID}-description`}>{props.description}</RN.Text>
      ) : null}
      {props.children}
    </RN.Pressable>
  );
  return { __esModule: true, default: MapViewMock, Marker: MarkerMock };
});

import ScheduleMap from "@/src/components/schedule/ScheduleMap.native";
import {
  jobPinVariant,
  isApproximatePin,
  propertyChipLabel,
  jobPinWrapStyle,
} from "@/src/utils/jobPinCoordSource";
import { deriveDarker } from "@/src/components/maps/TeardropPin";

const base = { status: "scheduled", address: "1 Main", location_lat: 33.4, location_lng: -112.0 };
const JOBS = [
  { ...base, id: "jp", customer_name: "Prop Co", coord_source: "property", property_id: "p1", property_label: "Lake House" },
  { ...base, id: "ja", customer_name: "Approx Co", coord_source: "customer", property_id: "p2", property_label: "Cabin", location_lat: 33.41 },
  { ...base, id: "jc", customer_name: "Single Co", coord_source: "customer", property_id: null, location_lat: 33.42 },
  { ...base, id: "jj", customer_name: "Job Co", coord_source: "job", property_id: "p3", property_label: "Barn", location_lat: 33.43 },
];
const BLUE = "#2563EB";
const flat = (st: any) => Object.assign({}, ...[].concat(st).flat(Infinity).filter(Boolean));

describe("jobPinCoordSource · coord_source → style mapping", () => {
  it("property rung → normal pin (opacity 1, transparent solid ring)", () => {
    expect(jobPinVariant(JOBS[0])).toBe("property");
    expect(jobPinWrapStyle(JOBS[0], BLUE)).toMatchObject({
      opacity: 1, borderStyle: "solid", borderColor: "transparent", borderWidth: 2,
    });
  });

  it("customer + property_id → approximate (70% opacity, dashed darker ring)", () => {
    expect(jobPinVariant(JOBS[1])).toBe("approximate");
    expect(jobPinWrapStyle(JOBS[1], BLUE)).toMatchObject({
      opacity: 0.7, borderStyle: "dashed", borderColor: deriveDarker(BLUE), borderWidth: 2,
    });
  });

  it("customer alone / job / null → normal pin, no flag", () => {
    for (const j of [JOBS[2], JOBS[3], { coord_source: null }, {}, null]) {
      expect(jobPinVariant(j as any)).toBe("normal");
      expect(jobPinWrapStyle(j as any, BLUE)).toMatchObject({ opacity: 1, borderStyle: "solid" });
    }
  });

  it("approximate fires ONLY on customer + truthy property_id", () => {
    expect(isApproximatePin({ coord_source: "customer", property_id: "p" })).toBe(true);
    expect(isApproximatePin({ coord_source: "customer", property_id: null })).toBe(false);
    expect(isApproximatePin({ coord_source: "customer", property_id: "" })).toBe(false);
    expect(isApproximatePin({ coord_source: "property", property_id: "p" })).toBe(false);
    expect(isApproximatePin({ coord_source: "job", property_id: "p" })).toBe(false);
    expect(isApproximatePin({ coord_source: null, property_id: "p" })).toBe(false);
  });

  it("property chip label only on property rung with a label", () => {
    expect(propertyChipLabel(JOBS[0])).toBe("Lake House");
    expect(propertyChipLabel(JOBS[1])).toBeNull(); // approximate, label suppressed
    expect(propertyChipLabel(JOBS[3])).toBeNull(); // job rung
    expect(propertyChipLabel({ coord_source: "property", property_label: null })).toBeNull();
  });
});

describe("ScheduleMap · multi-property pins", () => {
  it("renders approximate styling only on the customer+property_id pin", () => {
    const { getByTestId } = render(<ScheduleMap jobs={JOBS} />);
    expect(flat(getByTestId("schedule-map-pin-wrap-ja").props.style).opacity).toBe(0.7);
    expect(flat(getByTestId("schedule-map-pin-wrap-ja").props.style).borderStyle).toBe("dashed");
    expect(getByTestId("schedule-map-pin-wrap-ja").props.accessibilityLabel).toMatch(/approximate location/);
    for (const id of ["jp", "jc", "jj"]) {
      const st = flat(getByTestId(`schedule-map-pin-wrap-${id}`).props.style);
      expect(st.opacity).toBe(1);
      expect(st.borderStyle).toBe("solid");
    }
  });

  it("property_label shows as callout description + info-card chip (property rung only)", () => {
    const { getByTestId, queryByTestId } = render(<ScheduleMap jobs={JOBS} />);
    expect(getByTestId("schedule-map-pin-jp-description").props.children).toBe("Lake House");
    expect(queryByTestId("schedule-map-pin-ja-description")).toBeNull();
    expect(queryByTestId("schedule-map-pin-jj-description")).toBeNull();

    fireEvent.press(getByTestId("schedule-map-pin-jp"));
    const chip = getByTestId("schedule-map-info-property-jp");
    expect(within(chip).getByText("Lake House")).toBeTruthy();
    expect(within(chip).getByText(/Property:/)).toBeTruthy();
    expect(queryByTestId("schedule-map-info-approximate-jp")).toBeNull();
  });

  it("approximate pin card shows the approximate note, no property chip", () => {
    const { getByTestId, queryByTestId } = render(<ScheduleMap jobs={JOBS} />);
    fireEvent.press(getByTestId("schedule-map-pin-ja"));
    expect(getByTestId("schedule-map-info-approximate-ja")).toBeTruthy();
    expect(queryByTestId("schedule-map-info-property-ja")).toBeNull();
  });

  it("customer-only and job-rung cards show neither chip nor note", () => {
    const { getByTestId, queryByTestId } = render(<ScheduleMap jobs={JOBS} />);
    for (const id of ["jc", "jj"]) {
      fireEvent.press(getByTestId(`schedule-map-pin-${id}`));
      expect(queryByTestId(`schedule-map-info-property-${id}`)).toBeNull();
      expect(queryByTestId(`schedule-map-info-approximate-${id}`)).toBeNull();
    }
  });
});
