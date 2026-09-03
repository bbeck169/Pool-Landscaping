/**
 * K36 · Schedule crash hardening — ScheduleErrorBoundary.
 *
 * Verifies:
 *   1. A render throw in a child surfaces the boundary card + testIDs.
 *   2. The boundary persists the crash into the diagnostic ring buffer.
 *   3. Tapping "Try Again" resets the boundary and re-renders children.
 */
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";
import { Text } from "react-native";

// diagnostics is dynamically hit via persistCrash(); mock it so we can
// assert without touching AsyncStorage inside the test environment.
jest.mock("@/src/utils/diagnostics", () => ({
  persistCrash: jest.fn(),
  logNav: jest.fn(),
}));

// Silence the intentional console.warn from componentDidCatch so the
// Jest run log stays clean.
const originalWarn = console.warn;
const originalError = console.error;
beforeAll(() => {
  console.warn = jest.fn();
  console.error = jest.fn();
});
afterAll(() => {
  console.warn = originalWarn;
  console.error = originalError;
});

import { ScheduleErrorBoundary } from "@/src/components/ScheduleErrorBoundary";
import { persistCrash, logNav } from "@/src/utils/diagnostics";

function Boom({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("kaboom — null tenant");
  return <Text testID="boom-ok">ok</Text>;
}

describe("ScheduleErrorBoundary", () => {
  beforeEach(() => {
    (persistCrash as jest.Mock).mockClear();
    (logNav as jest.Mock).mockClear();
  });

  it("renders children when they don't throw", () => {
    const { getByTestId, queryByTestId } = render(
      <ScheduleErrorBoundary>
        <Boom shouldThrow={false} />
      </ScheduleErrorBoundary>,
    );
    expect(getByTestId("boom-ok")).toBeTruthy();
    expect(queryByTestId("schedule-error-boundary")).toBeNull();
    expect(persistCrash).not.toHaveBeenCalled();
  });

  it("catches a render throw and shows the error card", () => {
    const { getByTestId } = render(
      <ScheduleErrorBoundary>
        <Boom shouldThrow={true} />
      </ScheduleErrorBoundary>,
    );
    expect(getByTestId("schedule-error-boundary")).toBeTruthy();
    const msg = getByTestId("schedule-error-boundary-message");
    expect(msg.props.children).toContain("kaboom");
  });

  it("persists the crash into the diagnostic ring buffer", () => {
    render(
      <ScheduleErrorBoundary>
        <Boom shouldThrow={true} />
      </ScheduleErrorBoundary>,
    );
    expect(persistCrash).toHaveBeenCalledTimes(1);
    const [err] = (persistCrash as jest.Mock).mock.calls[0];
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("kaboom — null tenant");
    expect(logNav).toHaveBeenCalledWith(
      "schedule.error-boundary.caught",
      expect.objectContaining({ message: expect.stringContaining("kaboom") }),
    );
  });

  it("Try Again resets the boundary and re-renders children", () => {
    // Wrap the child so we can flip `shouldThrow` after the retry.
    function Harness() {
      const [broken, setBroken] = React.useState(true);
      return (
        <ScheduleErrorBoundary onReset={() => setBroken(false)}>
          <Boom shouldThrow={broken} />
        </ScheduleErrorBoundary>
      );
    }
    const { getByTestId, queryByTestId } = render(<Harness />);
    expect(getByTestId("schedule-error-boundary")).toBeTruthy();
    act(() => {
      fireEvent.press(getByTestId("schedule-error-boundary-retry"));
    });
    expect(queryByTestId("schedule-error-boundary")).toBeNull();
    expect(getByTestId("boom-ok")).toBeTruthy();
    expect(logNav).toHaveBeenCalledWith("schedule.error-boundary.retry");
  });
});
