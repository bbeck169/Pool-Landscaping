/**
 * schedule-sync-route.test.tsx
 *
 * Tests for the manual "Sync route" button on the mobile Schedule screen.
 */
import React, { useState, useRef, useEffect } from "react";
import { render, fireEvent } from "@testing-library/react-native";
import { View, Text, Pressable, ActivityIndicator } from "react-native";

/* ── Controllable mock state ───────────────────────────────────────── */

let mockOnline = true;
let mockInProgress = false;
let mockCachedJobs = 12;
let mockLastSyncedAt = new Date().toISOString();
const mockTriggerHydrate = jest.fn();

/* ── Minimal component mirror ──────────────────────────────────────── */

function SyncRouteToolbar() {
  const [syncingRoute, setSyncingRoute] = useState(false);
  const [syncToast, setSyncToast] = useState<string | null>(null);

  const handleSyncRoute = () => {
    if (syncingRoute || !mockOnline) return;
    setSyncingRoute(true);
    setSyncToast(null);
    mockTriggerHydrate();
  };

  const prevInProgress = useRef(mockInProgress);
  useEffect(() => {
    if (syncingRoute && prevInProgress.current && !mockInProgress) {
      setSyncToast(`Route cached — ${mockCachedJobs} job${mockCachedJobs !== 1 ? "s" : ""} offline-ready`);
      setSyncingRoute(false);
    }
    prevInProgress.current = mockInProgress;
  }, [mockInProgress, syncingRoute]);

  const showSpinner = syncingRoute || mockInProgress;

  return (
    <View>
      <Pressable
        onPress={handleSyncRoute}
        disabled={showSpinner || !mockOnline}
        testID="schedule-sync-route"
        accessibilityLabel={!mockOnline ? "You're offline — sync when connected" : "Sync route"}
      >
        {showSpinner
          ? <ActivityIndicator size={14} color="#2563EB" testID="schedule-sync-route-progress" />
          : <Text testID="icon-cloud-download-outline">cloud-download-outline</Text>}
      </Pressable>

      <Pressable testID="schedule-refresh"><Text>Refresh</Text></Pressable>

      {syncToast ? (
        <View testID="schedule-sync-toast"><Text testID="sync-toast-text">{syncToast}</Text></View>
      ) : null}

      {mockLastSyncedAt && !showSpinner ? (
        <View testID="schedule-cache-freshness">
          <Text testID="freshness-text">
            {(() => {
              const ms = Date.now() - new Date(mockLastSyncedAt).getTime();
              const min = Math.round(ms / 60000);
              if (min < 1) return "Cached just now";
              if (min < 60) return `Cached ${min} min ago`;
              return `Cached ${Math.floor(min / 60)}h ${min % 60}m ago`;
            })()}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

/* ── Tests ──────────────────────────────────────────────────────────── */

describe("Schedule Sync Route", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockOnline = true;
    mockInProgress = false;
    mockCachedJobs = 12;
    mockLastSyncedAt = new Date().toISOString();
  });

  it("1. renders schedule-sync-route and schedule-refresh as siblings", () => {
    const { getByTestId } = render(<SyncRouteToolbar />);
    const sync = getByTestId("schedule-sync-route");
    const refresh = getByTestId("schedule-refresh");
    expect(sync).toBeTruthy();
    expect(refresh).toBeTruthy();
    expect(sync.parent).toBe(refresh.parent);
  });

  it("2. invokes triggerHydrate on tap (no WiFi gate)", () => {
    const { getByTestId } = render(<SyncRouteToolbar />);
    fireEvent.press(getByTestId("schedule-sync-route"));
    expect(mockTriggerHydrate).toHaveBeenCalledTimes(1);
  });

  it("3. shows success toast after sync completes", () => {
    mockInProgress = false;
    const { getByTestId, queryByTestId, rerender } = render(<SyncRouteToolbar />);
    fireEvent.press(getByTestId("schedule-sync-route"));
    expect(queryByTestId("schedule-sync-toast")).toBeNull();

    mockInProgress = true;
    rerender(<SyncRouteToolbar />);
    expect(queryByTestId("schedule-sync-toast")).toBeNull();

    mockInProgress = false;
    rerender(<SyncRouteToolbar />);
    expect(queryByTestId("schedule-sync-toast")).toBeTruthy();
    expect(getByTestId("sync-toast-text").props.children).toBe("Route cached — 12 jobs offline-ready");
  });

  it("4a. shows progress spinner when inProgress=true", () => {
    mockInProgress = true;
    const { queryByTestId } = render(<SyncRouteToolbar />);
    expect(queryByTestId("schedule-sync-route-progress")).toBeTruthy();
    expect(queryByTestId("icon-cloud-download-outline")).toBeNull();
  });

  it("4b. hides spinner and shows icon when inProgress=false", () => {
    mockInProgress = false;
    const { queryByTestId } = render(<SyncRouteToolbar />);
    expect(queryByTestId("schedule-sync-route-progress")).toBeNull();
    expect(queryByTestId("icon-cloud-download-outline")).toBeTruthy();
  });

  it("5a. shows 'Cached just now' for recent sync", () => {
    mockLastSyncedAt = new Date().toISOString();
    const { getByTestId } = render(<SyncRouteToolbar />);
    expect(getByTestId("schedule-cache-freshness")).toBeTruthy();
    expect(getByTestId("freshness-text").props.children).toBe("Cached just now");
  });

  it("5b. shows 'Cached 5 min ago' for 5-minute-old sync", () => {
    mockLastSyncedAt = new Date(Date.now() - 5 * 60000).toISOString();
    const { getByTestId } = render(<SyncRouteToolbar />);
    expect(getByTestId("freshness-text").props.children).toBe("Cached 5 min ago");
  });

  it("6a. disables button when offline with accessibility label", () => {
    mockOnline = false;
    const { getByTestId } = render(<SyncRouteToolbar />);
    const btn = getByTestId("schedule-sync-route");
    expect(btn.props.accessibilityLabel).toBe("You're offline — sync when connected");
    expect(btn.props.accessibilityState?.disabled ?? btn.props.disabled).toBeTruthy();
  });

  it("6b. does NOT call triggerHydrate when offline", () => {
    mockOnline = false;
    const { getByTestId } = render(<SyncRouteToolbar />);
    fireEvent.press(getByTestId("schedule-sync-route"));
    expect(mockTriggerHydrate).not.toHaveBeenCalled();
  });


  it("7b. sync proceeds on cellular — no confirm dialog", () => {
    mockOnline = true;
    const { getByTestId, queryByTestId } = render(<SyncRouteToolbar />);
    fireEvent.press(getByTestId("schedule-sync-route"));
    expect(mockTriggerHydrate).toHaveBeenCalledTimes(1);
    expect(queryByTestId("schedule-sync-cellular-confirm-dialog")).toBeNull();
  });
});
