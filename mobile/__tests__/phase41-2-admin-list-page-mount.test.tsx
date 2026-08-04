/**
 * Phase 41.2 · Feb-2026 — Mobile <AdminListPage> primitive mount test.
 *
 * Confirms in isolation that the shared primitive composes its
 * scaffold correctly:
 *   • wraps children in <RoleGate> (default level = "strict_admin")
 *   • renders a <Header> with the passed title
 *   • renders the loading spinner when loading=true
 *   • renders <EmptyState> when isEmpty=true and loading=false
 *   • renders children when loading=false and isEmpty=false
 *   • fires onCreate from the Header's right-slot create button
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";
import { Text } from "react-native";

// Stub the RoleGate so the test does not need the real auth context —
// the primitive's contract is that it *renders* a <RoleGate>, not
// that it verifies auth. We tag it so we can assert the level prop.
jest.mock("@/src/components/RoleGate", () => {
  const { View } = require("react-native");
  return {
    __esModule: true,
    RoleGate: ({ level, children }: any) => (
      <View testID={`role-gate-${level}`}>{children}</View>
    ),
  };
});

// Stub the shared UI + widget modules so the test only exercises the
// primitive's composition rules — not the visuals of Loading /
// EmptyState / Header / IconButton.
jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: () => <Text testID="stub-loading">Loading</Text>,
    EmptyState: ({ title, testID }: any) => (
      <View testID={testID || "stub-empty"}>
        <Text>{title}</Text>
      </View>
    ),
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Header: ({ title, right }: any) => (
      <View testID="stub-header">
        <Text>{title}</Text>
        {right}
      </View>
    ),
    IconButton: ({ onPress, testID }: any) => (
      <Pressable onPress={onPress} testID={testID}>
        <Text>+</Text>
      </Pressable>
    ),
  };
});

// eslint-disable-next-line import/first
import { AdminListPage } from "@/src/components/layout/AdminListPage";

describe("Phase 41.2 · <AdminListPage> mount", () => {
  const baseProps = {
    title: "Test Page",
    testID: "test-page",
    refreshing: false,
    onRefresh: () => {},
    emptyIcon: "sparkles",
    emptyTitle: "Nothing here",
    emptyTestID: "test-empty",
  };

  it("wraps in <RoleGate level='strict_admin'> by default", () => {
    const { getByTestId } = render(
      <AdminListPage {...baseProps} loading={false} isEmpty={false}>
        <Text testID="body">rows</Text>
      </AdminListPage>,
    );
    // Default gate + wrapper testID + body all present.
    expect(getByTestId("role-gate-strict_admin")).toBeTruthy();
    expect(getByTestId("test-page")).toBeTruthy();
    expect(getByTestId("body")).toBeTruthy();
  });

  it("renders the Header with the title", () => {
    const { getByTestId, getByText } = render(
      <AdminListPage {...baseProps} loading={false} isEmpty={false}>
        <Text>rows</Text>
      </AdminListPage>,
    );
    expect(getByTestId("stub-header")).toBeTruthy();
    expect(getByText("Test Page")).toBeTruthy();
  });

  it("renders the loading spinner when loading=true", () => {
    const { getByTestId, queryByTestId } = render(
      <AdminListPage {...baseProps} loading={true} isEmpty={false}>
        <Text testID="body">rows</Text>
      </AdminListPage>,
    );
    expect(getByTestId("stub-loading")).toBeTruthy();
    // Body is NOT rendered while loading.
    expect(queryByTestId("body")).toBeNull();
  });

  it("renders <EmptyState> when isEmpty=true and loading=false", () => {
    const { getByTestId, queryByTestId, getByText } = render(
      <AdminListPage {...baseProps} loading={false} isEmpty={true}>
        <Text testID="body">rows</Text>
      </AdminListPage>,
    );
    expect(getByTestId("test-empty")).toBeTruthy();
    expect(getByText("Nothing here")).toBeTruthy();
    expect(queryByTestId("body")).toBeNull();
  });

  it("renders children when loading=false and isEmpty=false", () => {
    const { getByTestId, queryByTestId } = render(
      <AdminListPage {...baseProps} loading={false} isEmpty={false}>
        <Text testID="body">rows</Text>
      </AdminListPage>,
    );
    expect(getByTestId("body")).toBeTruthy();
    expect(queryByTestId("stub-loading")).toBeNull();
    expect(queryByTestId("test-empty")).toBeNull();
  });

  it("wires onCreate to a Header right-slot IconButton", () => {
    const onCreate = jest.fn();
    const { getByTestId } = render(
      <AdminListPage
        {...baseProps}
        loading={false}
        isEmpty={false}
        onCreate={onCreate}
        createTestID="test-create"
      >
        <Text>rows</Text>
      </AdminListPage>,
    );
    fireEvent.press(getByTestId("test-create"));
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it("respects a caller-supplied roleLevel override", () => {
    const { getByTestId } = render(
      <AdminListPage {...baseProps} roleLevel="admin_plus" loading={false} isEmpty={false}>
        <Text>rows</Text>
      </AdminListPage>,
    );
    expect(getByTestId("role-gate-admin_plus")).toBeTruthy();
  });
});
