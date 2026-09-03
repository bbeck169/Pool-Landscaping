/**
 * K36 · Schedule crash hardening — 20-second loading watchdog.
 *
 * Verifies the fallback UI that swaps in after LOADING_WATCHDOG_MS
 * so the tech isn't left staring at "Loading…" for the whole watchdog
 * window (which was the pre-K36 iOS crash pattern).
 *
 * The Schedule calendar screen itself is a 1 700-LOC file that pulls
 * in react-native-maps, DraggableFlatList, expo-router, and the
 * offline SQLite cache — none of those are safe to run under
 * jest-expo. We recreate the contract for the loading state locally,
 * mirroring the JSX + testIDs the calendar screen uses.
 */
import React, { useEffect, useState } from "react";
import { render, fireEvent, act } from "@testing-library/react-native";
import { View, Text, Pressable, ActivityIndicator } from "react-native";

const LOADING_WATCHDOG_MS = 20_000;

/** Mirror of the loading branch inside `ScheduleCalendarInner`. */
function LoadingWithWatchdog({
  onRetry,
  onContinueOffline,
}: {
  onRetry: () => void;
  onContinueOffline: () => void;
}) {
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setTimedOut(true), LOADING_WATCHDOG_MS);
    return () => clearTimeout(t);
  }, []);

  if (timedOut) {
    return (
      <View testID="schedule-loading-timeout">
        <Text>Schedule is taking longer than usual</Text>
        <Pressable testID="schedule-loading-timeout-retry" onPress={onRetry}>
          <Text>Retry</Text>
        </Pressable>
        <Pressable
          testID="schedule-loading-timeout-continue"
          onPress={onContinueOffline}
        >
          <Text>Continue offline</Text>
        </Pressable>
      </View>
    );
  }
  return (
    <View testID="schedule-loading-spinner">
      <ActivityIndicator />
    </View>
  );
}

describe("Schedule loading watchdog", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it("shows the spinner initially and no fallback", () => {
    const { getByTestId, queryByTestId } = render(
      <LoadingWithWatchdog onRetry={jest.fn()} onContinueOffline={jest.fn()} />,
    );
    expect(getByTestId("schedule-loading-spinner")).toBeTruthy();
    expect(queryByTestId("schedule-loading-timeout")).toBeNull();
  });

  it("swaps to the fallback card after LOADING_WATCHDOG_MS", () => {
    const { getByTestId, queryByTestId } = render(
      <LoadingWithWatchdog onRetry={jest.fn()} onContinueOffline={jest.fn()} />,
    );
    act(() => {
      jest.advanceTimersByTime(LOADING_WATCHDOG_MS + 10);
    });
    expect(queryByTestId("schedule-loading-spinner")).toBeNull();
    expect(getByTestId("schedule-loading-timeout")).toBeTruthy();
    expect(getByTestId("schedule-loading-timeout-retry")).toBeTruthy();
    expect(getByTestId("schedule-loading-timeout-continue")).toBeTruthy();
  });

  it("does NOT swap in early (before 20s)", () => {
    const { queryByTestId } = render(
      <LoadingWithWatchdog onRetry={jest.fn()} onContinueOffline={jest.fn()} />,
    );
    act(() => {
      jest.advanceTimersByTime(LOADING_WATCHDOG_MS - 100);
    });
    expect(queryByTestId("schedule-loading-timeout")).toBeNull();
  });

  it("Retry button fires the retry handler", () => {
    const onRetry = jest.fn();
    const { getByTestId } = render(
      <LoadingWithWatchdog onRetry={onRetry} onContinueOffline={jest.fn()} />,
    );
    act(() => {
      jest.advanceTimersByTime(LOADING_WATCHDOG_MS + 10);
    });
    fireEvent.press(getByTestId("schedule-loading-timeout-retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("Continue offline button fires its handler", () => {
    const onContinue = jest.fn();
    const { getByTestId } = render(
      <LoadingWithWatchdog onRetry={jest.fn()} onContinueOffline={onContinue} />,
    );
    act(() => {
      jest.advanceTimersByTime(LOADING_WATCHDOG_MS + 10);
    });
    fireEvent.press(getByTestId("schedule-loading-timeout-continue"));
    expect(onContinue).toHaveBeenCalledTimes(1);
  });
});
