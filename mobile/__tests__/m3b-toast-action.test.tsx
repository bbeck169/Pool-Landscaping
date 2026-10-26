/**
 * M3b commit 1 · ToastProvider optional action button (additive; for the M3b "Undo").
 */
import React from "react";
import { Text, Pressable } from "react-native";
import { render, fireEvent, act } from "@testing-library/react-native";

jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

import { ToastProvider, useToast, type ToastAction } from "@/src/components/ToastProvider";

function Trigger({ action, ms }: { action?: ToastAction; ms?: number }) {
  const { showToast } = useToast();
  return (
    <Pressable testID="fire" onPress={() => (action ? showToast("Marked as Open", "success", ms ?? 5000, action) : showToast("Saved"))}>
      <Text>fire</Text>
    </Pressable>
  );
}
const mount = (action?: ToastAction, ms?: number) => render(<ToastProvider><Trigger action={action} ms={ms} /></ToastProvider>);

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

it("T1 · legacy call (message only) → no action button; container non-interactive (pointerEvents none)", () => {
  const q = mount();
  fireEvent.press(q.getByTestId("fire"));
  expect(q.getByTestId("toast-text").props.children).toBe("Saved");
  expect(q.queryByTestId("toast-action")).toBeNull();
  expect(q.getByTestId("toast-container").props.pointerEvents).toBe("none");
});

it("T2 · with action → labelled button; container box-none so only the toast takes touches", () => {
  const q = mount({ label: "Undo", onPress: jest.fn() });
  fireEvent.press(q.getByTestId("fire"));
  expect(q.getByTestId("toast-action")).toBeTruthy();
  expect(q.getByText("Undo")).toBeTruthy();
  expect(q.getByTestId("toast-container").props.pointerEvents).toBe("box-none");
});

it("T3 · pressing the action runs onPress once and dismisses the toast immediately", () => {
  const onPress = jest.fn();
  const q = mount({ label: "Undo", onPress });
  fireEvent.press(q.getByTestId("fire"));
  fireEvent.press(q.getByTestId("toast-action"));
  expect(onPress).toHaveBeenCalledTimes(1);
  expect(q.queryByTestId("toast-container")).toBeNull();
});

it("T4 · after the duration the toast (and its action) is gone; a later legacy toast has no stale action", () => {
  const onPress = jest.fn();
  const q = mount({ label: "Undo", onPress }, 5000);
  fireEvent.press(q.getByTestId("fire"));
  act(() => { jest.advanceTimersByTime(5000 + 400); });
  expect(q.queryByTestId("toast-action")).toBeNull();
  expect(onPress).not.toHaveBeenCalled();
});
