/**
 * TD-mobile-header-layout-cleanup · 320 / 375 / 414 width coverage (Schedule only).
 * Jest has no layout engine, so this pins (a) which controls sit in the title row
 * at each width and (b) the real shared Header's flex contract that guarantees the
 * title is the only shrinking element. Pixel truncation = live preview check.
 */
import React from "react";
import { View, StyleSheet } from "react-native";
import { render } from "@testing-library/react-native";

jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn(), back: jest.fn() }), useFocusEffect: jest.fn(), usePathname: () => "/schedule" }));
jest.mock("@/src/api", () => ({ api: { get: jest.fn() } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: "technician" } }) }));
jest.mock("@/src/components/nav/Breadcrumbs", () => () => null);
jest.mock("@/src/components/BrandLogo", () => () => null);
jest.mock("@/src/hooks/useBreadcrumbs", () => ({ useBreadcrumbs: () => [] }));
jest.mock("@/src/components/tools/GlobalMenu", () => ({ openGlobalMenu: jest.fn() }));
jest.mock("@/src/components/marco/MicToggleButton", () => ({ MicToggleButton: () => null }));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));

import { Header } from "@/src/components/widgets";
import { isCompactScheduleHeader, SCHEDULE_COMPACT_HEADER_MAX_DP } from "@/src/lib/scheduleHeader";

/** Mirrors calendar.tsx: routeActions live in the title row only when not compact. */
function ScheduleHeaderAt({ width }: { width: number }) {
  const compact = isCompactScheduleHeader(width);
  const routeActions = <View testID="route-actions" />;
  return (
    <View>
      <Header title="Schedule" right={
        <View testID="schedule-right" style={{ flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {!compact && routeActions}
          <View testID="schedule-header-bell" />
        </View>
      } />
      <View testID="schedule-status-strip">{compact && routeActions}</View>
    </View>
  );
}

const flat = (n: any) => StyleSheet.flatten(n.props.style) || {};

describe.each([
  [320, true],
  [375, false],
  [414, false],
])("width %i dp", (width, compact) => {
  it(`compact=${compact}: route actions in ${compact ? "strip" : "title row"}, bell always in title row`, () => {
    const q = render(<ScheduleHeaderAt width={width} />);
    expect(isCompactScheduleHeader(width)).toBe(compact);
    const right = q.getByTestId("schedule-right");
    const strip = q.getByTestId("schedule-status-strip");
    expect(!!right.findAll((n) => n.props.testID === "route-actions").length).toBe(!compact);
    expect(!!strip.findAll((n) => n.props.testID === "route-actions").length).toBe(compact);
    expect(q.getAllByTestId("route-actions")).toHaveLength(1);
    expect(right.findAll((n) => n.props.testID === "schedule-header-bell").length).toBeGreaterThan(0);
  });

  it("title is the only shrinking element: full 'Schedule' text, single line, shrinkable box; right cluster no-shrink, no fixed bell margin", () => {
    const q = render(<ScheduleHeaderAt width={width} />);
    const title = q.getByText("Schedule");
    expect(title.props.numberOfLines).toBe(1);
    let n: any = title.parent, hops = 0; // nearest View ancestor = the title box
    while (n && (n.type !== "View" || !n.props.style) && hops++ < 4) n = n.parent;
    expect(flat(n)).toMatchObject({ flex: 1, minWidth: 0, flexShrink: 1 });
    expect(flat(q.getByTestId("schedule-right")).flexShrink).toBe(0);
    // shared Header right cluster: RN default flexShrink 0 (never set to shrink)
    const shared = q.getByTestId("schedule-right").parent!;
    expect(flat(shared).flexShrink ?? 0).toBe(0);
    expect(flat(shared).marginRight ?? 0).not.toBe(52);
  });
});

it("threshold boundary: 359 compact, 360 not", () => {
  expect(SCHEDULE_COMPACT_HEADER_MAX_DP).toBe(360);
  expect(isCompactScheduleHeader(359)).toBe(true);
  expect(isCompactScheduleHeader(360)).toBe(false);
});
