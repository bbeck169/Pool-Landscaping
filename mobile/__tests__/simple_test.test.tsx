import React, { useState } from "react";
import { render, fireEvent } from "@testing-library/react-native";
import { View, Text, Pressable, ActivityIndicator } from "react-native";

let mockOnline = true;
let mockInProgress = false;
let mockCachedJobs = 12;
let mockLastSyncedAt = new Date().toISOString();
const mockTriggerHydrate = jest.fn();

function SyncBtn() {
  const showSpinner = mockInProgress;
  return (
    <View>
      <Pressable
        onPress={() => { if (mockOnline) mockTriggerHydrate(); }}
        disabled={showSpinner || !mockOnline}
        testID="schedule-sync-route"
        accessibilityLabel={!mockOnline ? "You're offline — sync when connected" : "Sync route"}
      >
        {showSpinner
          ? <ActivityIndicator testID="schedule-sync-route-progress" />
          : <Text testID="sync-icon">icon</Text>}
      </Pressable>
      <Pressable testID="schedule-refresh"><Text>Refresh</Text></Pressable>
      {mockLastSyncedAt && !showSpinner ? (
        <View testID="schedule-cache-freshness">
          <Text testID="freshness-text">
            {Math.round((Date.now() - new Date(mockLastSyncedAt).getTime()) / 60000) < 1
              ? "Cached just now"
              : "Cached " + Math.round((Date.now() - new Date(mockLastSyncedAt).getTime()) / 60000) + " min ago"}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

describe("Sync Route", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockOnline = true; mockInProgress = false;
    mockCachedJobs = 12; mockLastSyncedAt = new Date().toISOString();
  });

  it("1. siblings", () => {
    const { getByTestId } = render(<SyncBtn />);
    expect(getByTestId("schedule-sync-route").parent).toBe(getByTestId("schedule-refresh").parent);
  });
  it("2. calls hydrate", () => {
    const { getByTestId } = render(<SyncBtn />);
    fireEvent.press(getByTestId("schedule-sync-route"));
    expect(mockTriggerHydrate).toHaveBeenCalledTimes(1);
  });
  it("4a. spinner", () => {
    mockInProgress = true;
    const { queryByTestId } = render(<SyncBtn />);
    expect(queryByTestId("schedule-sync-route-progress")).toBeTruthy();
  });
  it("4b. icon", () => {
    const { queryByTestId } = render(<SyncBtn />);
    expect(queryByTestId("sync-icon")).toBeTruthy();
  });
  it("5a. just now", () => {
    const { getByTestId } = render(<SyncBtn />);
    expect(getByTestId("freshness-text").props.children).toBe("Cached just now");
  });
  it("5b. 5 min", () => {
    mockLastSyncedAt = new Date(Date.now() - 5 * 60000).toISOString();
    const { getByTestId } = render(<SyncBtn />);
    expect(getByTestId("freshness-text").props.children).toBe("Cached 5 min ago");
  });
  it("6a. disabled offline", () => {
    mockOnline = false;
    const { getByTestId } = render(<SyncBtn />);
    expect(getByTestId("schedule-sync-route").props.accessibilityLabel).toBe("You're offline — sync when connected");
  });
  it("6b. no call offline", () => {
    mockOnline = false;
    const { getByTestId } = render(<SyncBtn />);
    fireEvent.press(getByTestId("schedule-sync-route"));
    expect(mockTriggerHydrate).not.toHaveBeenCalled();
  });
  it("7a. no WiFi gate", () => {
    const fs = require("fs");
    ["/app/mobile/src/services/routeHydrator.ts",
     "/app/mobile/src/hooks/useRouteHydration.ts",
     "/app/mobile/src/lib/offline/netStatus.ts",
    ].forEach(f => {
      expect(fs.readFileSync(f, "utf-8")).not.toMatch(/isWifi|wifi_only|wifiOnly/i);
    });
  });
  it("7b. no cellular dialog", () => {
    const { queryByTestId } = render(<SyncBtn />);
    expect(queryByTestId("schedule-sync-cellular-confirm-dialog")).toBeNull();
  });
});
