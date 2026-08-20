/**
 * Feb-2026 · Schedule polish — Notes call-out + gate-code badge (mobile).
 *
 * Mirror of the web test. The full ``calendar.tsx`` schedule
 * screen is a 1 300-LOC file that pulls in react-native-maps and
 * DraggableFlatList; we render only the JSX contract this task
 * introduced, using the same testIDs the schedule row uses.
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";
import { View, Text, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";


// Ionicons rendered inline pulls in Font.loadAsync at module init,
// which chokes under jest-expo. Stub it to a plain View to keep the
// test tree light.
jest.mock("@expo/vector-icons", () => {
  const RN = require("react-native");
  const React = require("react");
  return {
    Ionicons: ({ name, size, color }: any) =>
      React.createElement(RN.View, { accessibilityLabel: `ionicons-${name}` }),
  };
});


/** Mirror of the mobile card block introduced by the task. */
function ScheduleCardNotesBlock({ job }: any) {
  const code = job.customer_gate_code || job.gate_code;
  const access = job.access_notes;
  const jobNote = job.notes && String(job.notes).trim() ? String(job.notes) : "";
  const custNote = (job.customer_notes || job.account_notes)
    ? String(job.customer_notes || job.account_notes).trim() : "";
  const full = [
    jobNote ? jobNote + (job.notes_truncated ? "…" : "") : "",
    custNote ? `Customer note: ${custNote}` : "",
  ].filter(Boolean).join("\n\n");

  return (
    <View>
      {(code || access) ? (
        <View testID={`job-gate-code-${job.id}`}>
          <Ionicons name="key-outline" size={11} color="#78350F" />
          {code
            ? <Text>Gate: {code}</Text>
            : <Text>Access</Text>}
          {access ? (
            <Text testID={`job-access-notes-${job.id}`}>{` · ${access}`}</Text>
          ) : null}
        </View>
      ) : null}
      {(jobNote || custNote) ? (
        <Pressable
          testID={`job-notes-callout-${job.id}`}
          onPress={() => Alert.alert("Notes", full)}
        >
          <Ionicons name="document-text-outline" size={12} color="#2563EB" />
          <View>
            {jobNote ? (
              <Text testID={`job-${job.id}-notes`} numberOfLines={2}>
                {jobNote}{job.notes_truncated ? "…" : ""}
              </Text>
            ) : null}
            {custNote ? (
              <Text testID={`job-notes-preview-${job.id}`} numberOfLines={2}>
                <Text>Customer note: </Text>{custNote}
              </Text>
            ) : null}
          </View>
        </Pressable>
      ) : null}
    </View>
  );
}


describe("Mobile schedule polish · gate-code badge", () => {
  test("renders when gate_code is present", () => {
    const { getByTestId } = render(
      <ScheduleCardNotesBlock job={{ id: "j1", gate_code: "1234" }} />,
    );
    expect(getByTestId("job-gate-code-j1")).toBeTruthy();
  });

  test("renders access_notes suffix", () => {
    const { getByTestId } = render(
      <ScheduleCardNotesBlock job={{
        id: "j2", gate_code: "5678", access_notes: "Use side gate",
      }} />,
    );
    expect(getByTestId("job-access-notes-j2")).toBeTruthy();
  });

  test("hides badge when neither field is set", () => {
    const { queryByTestId } = render(
      <ScheduleCardNotesBlock job={{ id: "j3" }} />,
    );
    expect(queryByTestId("job-gate-code-j3")).toBeNull();
  });
});


describe("Mobile schedule polish · notes call-out", () => {
  test("renders both job + customer notes with prefix", () => {
    const { getByTestId } = render(
      <ScheduleCardNotesBlock job={{
        id: "j4",
        notes: "Bring the acid tester.",
        customer_notes: "Dog in yard, use side gate.",
      }} />,
    );
    expect(getByTestId("job-notes-callout-j4")).toBeTruthy();
    expect(getByTestId("job-j4-notes").props.children.filter(Boolean).join(""))
      .toMatch(/Bring the acid tester/);
    // The customer-note row includes the "Customer note: " prefix.
    const custRow = getByTestId("job-notes-preview-j4");
    const kids = React.Children.toArray(custRow.props.children).flat();
    const flat = kids
      .map((c: any) => (typeof c === "string" ? c : c?.props?.children || ""))
      .join("");
    expect(flat).toMatch(/Customer note:/);
    expect(flat).toMatch(/Dog in yard/);
  });

  test("tap opens Alert with the full unclamped text", () => {
    const alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => {});
    const { getByTestId } = render(
      <ScheduleCardNotesBlock job={{
        id: "j5",
        notes: "Long job note.",
        customer_notes: "Long customer note.",
      }} />,
    );
    fireEvent.press(getByTestId("job-notes-callout-j5"));
    expect(alertSpy).toHaveBeenCalledWith("Notes",
      expect.stringMatching(/Long job note.*Customer note: Long customer note/s));
    alertSpy.mockRestore();
  });

  test("hides the call-out when no note is present anywhere", () => {
    const { queryByTestId } = render(
      <ScheduleCardNotesBlock job={{ id: "j6" }} />,
    );
    expect(queryByTestId("job-notes-callout-j6")).toBeNull();
  });
});
