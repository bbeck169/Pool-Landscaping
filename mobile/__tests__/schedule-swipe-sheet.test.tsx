/**
 * Schedule declutter (S3a) · SwipeSheet — RN Modal + PanResponder.
 * Dismiss on backdrop tap, close button, and swipe-down release rule.
 */
import React from "react";
import { Animated, Text } from "react-native";
import { render, fireEvent } from "@testing-library/react-native";

import SwipeSheet, { createSwipeConfig, shouldCloseOnRelease, SWIPE_CLOSE_PX } from "@/src/components/schedule/SwipeSheet";

function mount(onClose = jest.fn(), visible = true) {
  const q = render(
    <SwipeSheet visible={visible} onClose={onClose} title="Filters" testID="schedule-filters-sheet">
      <Text testID="sheet-child">child</Text>
    </SwipeSheet>,
  );
  return { q, onClose };
}

describe("SwipeSheet", () => {
  it("renders title + children when visible; nothing when hidden", () => {
    const { q } = mount();
    expect(q.getByText("Filters")).toBeTruthy();
    expect(q.getByTestId("sheet-child")).toBeTruthy();
    expect(mount(jest.fn(), false).q.queryByTestId("sheet-child")).toBeNull();
  });

  it("backdrop tap dismisses", () => {
    const { q, onClose } = mount();
    fireEvent.press(q.getByTestId("schedule-filters-sheet-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("close button dismisses and is labelled", () => {
    const { q, onClose } = mount();
    const btn = q.getByTestId("schedule-filters-sheet-close");
    expect(btn.props.accessibilityLabel).toBe("Close filters");
    fireEvent.press(btn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("swipe-down: release past the threshold or a fast flick dismisses; short drag snaps back", () => {
    expect(shouldCloseOnRelease(SWIPE_CLOSE_PX + 1, 0)).toBe(true);
    expect(shouldCloseOnRelease(10, 1.2)).toBe(true);
    expect(shouldCloseOnRelease(30, 0.1)).toBe(false);
    const onClose = jest.fn();
    const dragY = new Animated.Value(0);
    const cfg = createSwipeConfig(onClose, dragY);
    expect(cfg.onMoveShouldSetPanResponder(null, { dy: 20, dx: 2 })).toBe(true);
    expect(cfg.onMoveShouldSetPanResponder(null, { dy: 3, dx: 30 })).toBe(false); // horizontal → not ours
    cfg.onPanResponderMove(null, { dy: 50 });
    expect((dragY as any).__getValue()).toBe(50);
    cfg.onPanResponderRelease(null, { dy: 30, vy: 0.1 });
    expect(onClose).not.toHaveBeenCalled();
    cfg.onPanResponderRelease(null, { dy: 140, vy: 0.2 });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("pan handlers live on the grabber/header only (content stays scrollable)", () => {
    const { q } = mount();
    const handle = q.getByTestId("schedule-filters-sheet-handle");
    expect(typeof handle.props.onResponderRelease).toBe("function");
    expect(q.getByTestId("sheet-child").props.onResponderRelease).toBeUndefined();
  });
});
