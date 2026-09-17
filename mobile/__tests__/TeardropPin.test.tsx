/**
 * TeardropPin — unit tests (react-native-svg).
 *
 * Tests: default render, labeled pin, selected state, custom color,
 * helper exports.
 */
import React from "react";
import { render } from "@testing-library/react-native";
import TeardropPin, {
  colorFromId,
  deriveDarker,
  mixWithWhite,
  formatPinLabel,
  pickLabelTextColor,
} from "@/src/components/maps/TeardropPin";

/* react-native-svg mocks (just capture props) */
jest.mock("react-native-svg", () => {
  /* eslint-disable @typescript-eslint/no-require-imports */
  const { View, Text } = require("react-native");
  const svgFactory = (name: string) => {
    const Comp = (props: any) => {
      const { children, testID, ...rest } = props;
      return (
        <View testID={testID} {...rest}>
          {children}
        </View>
      );
    };
    Comp.displayName = name;
    return Comp;
  };

  return {
    __esModule: true,
    default: svgFactory("Svg"),
    Svg: svgFactory("Svg"),
    Path: svgFactory("Path"),
    Circle: svgFactory("Circle"),
    Ellipse: svgFactory("Ellipse"),
    Rect: svgFactory("Rect"),
    G: svgFactory("G"),
    Defs: svgFactory("Defs"),
    LinearGradient: svgFactory("LinearGradient"),
    RadialGradient: svgFactory("RadialGradient"),
    Stop: svgFactory("Stop"),
    Text: (props: any) => <Text testID={props.testID}>{props.children}</Text>,
  };
});

jest.mock("react-native-reanimated", () => {
  /* eslint-disable @typescript-eslint/no-require-imports */
  const { View } = require("react-native");
  return {
    __esModule: true,
    default: {
      View: View,
      createAnimatedComponent: (c: any) => c,
    },
    useSharedValue: (v: any) => ({ value: v }),
    useAnimatedStyle: (fn: any) => fn(),
    withRepeat: (a: any) => a,
    withTiming: (v: any) => v,
    Easing: { out: (e: any) => e, ease: 0 },
  };
});

describe("TeardropPin component", () => {
  it("renders default (no label) without crashing", () => {
    const { getByTestId } = render(
      <TeardropPin color="#3B82F6" testID="pin" />
    );
    expect(getByTestId("pin")).toBeTruthy();
    expect(getByTestId("pin-svg")).toBeTruthy();
    expect(getByTestId("pin-body")).toBeTruthy();
    expect(getByTestId("pin-shadow")).toBeTruthy();
  });

  it("renders with label centered inside the white disc", () => {
    const { getByTestId } = render(
      <TeardropPin color="#EF4444" label={3} testID="pin" />
    );
    expect(getByTestId("pin-disc")).toBeTruthy();
    expect(getByTestId("pin-label")).toBeTruthy();
    // Label should be zero-padded single digit
    expect(getByTestId("pin-label").children[0]).toBe("03");
  });

  it("selected=true adds scale transform to the group", () => {
    const { getByTestId } = render(
      <TeardropPin color="#10B981" selected testID="pin" />
    );
    const group = getByTestId("pin-group");
    expect(group.props.transform).toContain("scale(1.10)");
  });

  it("custom color propagates to fill / accessibilityLabel", () => {
    const { getByTestId } = render(
      <TeardropPin color="#6366F1" label="A" testID="pin" />
    );
    const pin = getByTestId("pin");
    expect(pin.props.accessibilityLabel).toContain("#6366F1");
    expect(pin.props.accessibilityLabel).toContain("A");
  });

  it("renders pulse halo when pulse=true", () => {
    const { getByTestId } = render(
      <TeardropPin color="#EC4899" pulse testID="pin" />
    );
    expect(getByTestId("teardrop-pin-pulse-halo")).toBeTruthy();
  });

  it("does not render pulse when pulse=false", () => {
    const { queryByTestId } = render(
      <TeardropPin color="#EC4899" testID="pin" />
    );
    expect(queryByTestId("teardrop-pin-pulse-halo")).toBeNull();
  });
});

describe("TeardropPin helper exports", () => {
  it("colorFromId returns deterministic palette color", () => {
    expect(colorFromId("tech-1")).toMatch(/^#/);
    expect(colorFromId("tech-1")).toBe(colorFromId("tech-1"));
    expect(colorFromId(null)).toMatch(/^#/);
  });

  it("deriveDarker darkens a hex", () => {
    const darker = deriveDarker("#3B82F6", 0.28);
    expect(darker).toMatch(/^#/);
    expect(darker).not.toBe("#3B82F6");
  });

  it("mixWithWhite(hex, 0.5) lightens toward white", () => {
    const lighter = mixWithWhite("#000000", 0.5);
    // Each channel should be ~128 → ~#808080
    expect(lighter).toMatch(/^#/);
    expect(lighter).not.toBe("#000000");
  });

  it("mixWithWhite(#FFFFFF, -1.0) darkens to black", () => {
    expect(mixWithWhite("#FFFFFF", -1.0)).toBe("#000000");
  });

  it("formatPinLabel pads single digits", () => {
    expect(formatPinLabel(1)).toBe("01");
    expect(formatPinLabel(10)).toBe("10");
    expect(formatPinLabel("A")).toBe("A");
    expect(formatPinLabel(null)).toBeNull();
    expect(formatPinLabel("")).toBeNull();
  });

  it("pickLabelTextColor chooses white for dark bg, dark for light bg", () => {
    expect(pickLabelTextColor("#000000")).toBe("#FFFFFF");
    expect(pickLabelTextColor("#FFFFFF")).toBe("#0F172A");
  });
});
