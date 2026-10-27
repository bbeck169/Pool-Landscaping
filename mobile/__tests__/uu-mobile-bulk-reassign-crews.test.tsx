/**
 * UU-mobile 3/3 · crews + techs in the Schedule bulk-reassign picker (web
 * `schedule-bulk-reassign-crew.test.jsx` parity). Picker rows rendered for real;
 * calendar.tsx wiring pinned by source lock (no screen render harness — baseline).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, fireEvent } from "@testing-library/react-native";

jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

import ReassignPickerList from "@/src/components/schedule/ReassignPickerList";
import { bulkReassignPayload, reassignRoleLabel } from "@/src/lib/bulkReassign";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
const CREWS = [{ id: "c1", name: "Blue Crew", color: "#00f", tech_ids: ["t1"], members: [] }, { id: "c2", name: "", tech_ids: [] }];
const TECHS = [{ id: "t1", name: "Mike", role: "pool_tech" }, { id: "t2", name: "Lara", role: "landscape_tech" }, { id: "t3", name: "Tom", role: "technician" }];
const mount = (p: any = {}) => {
  const onPickTech = jest.fn(); const onPickCrew = jest.fn();
  const q = render(<ReassignPickerList crews={CREWS} techs={TECHS} pickedTechId="" pickedCrewId="" onPickTech={onPickTech} onPickCrew={onPickCrew} {...p} />);
  return { q, onPickTech, onPickCrew };
};
const sub = (q: any, id: string) => q.getByTestId(`${id}-sublabel`).props.children;

it("U1 · list merges crews (first) + techs with sub-labels: literal 'crew' vs role", () => {
  const { q } = mount();
  const ids = q.UNSAFE_root.findAll((n: any) => typeof n.props?.testID === "string" && /^reassign-(crew|tech)-[^-]+$/.test(n.props.testID) && n.type !== "View")
    .map((n: any) => n.props.testID).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i);
  expect(ids).toEqual(["reassign-crew-c1", "reassign-crew-c2", "reassign-tech-t1", "reassign-tech-t2", "reassign-tech-t3"]);
  expect(sub(q, "reassign-crew-c1")).toBe("crew");
  expect(sub(q, "reassign-crew-c2")).toBe("crew");
  expect(sub(q, "reassign-tech-t1")).toBe("pool tech");
  expect(sub(q, "reassign-tech-t2")).toBe("landscape tech");
  expect(sub(q, "reassign-tech-t3")).toBe("technician");
  expect(q.getByText("Blue Crew")).toBeTruthy();
  expect(q.getByText("Unnamed crew")).toBeTruthy();
});

it("U2 · crew pick → onPickCrew(id) → payload { job_ids, new_crew_id } (no new_tech_id)", () => {
  const { q, onPickCrew, onPickTech } = mount();
  fireEvent.press(q.getByTestId("reassign-crew-c1"));
  expect(onPickCrew).toHaveBeenCalledWith("c1");
  expect(onPickTech).not.toHaveBeenCalled();
  const p = bulkReassignPayload(["j1", "j2"], { kind: "crew", id: "c1" });
  expect(p).toEqual({ job_ids: ["j1", "j2"], new_crew_id: "c1" });
  expect("new_tech_id" in p).toBe(false);
});

it("U3 · tech pick still → payload { job_ids, new_tech_id } (regression lock; no new_crew_id)", () => {
  const { q, onPickTech } = mount();
  fireEvent.press(q.getByTestId("reassign-tech-t2"));
  expect(onPickTech).toHaveBeenCalledWith("t2");
  const p = bulkReassignPayload(["j1"], { kind: "tech", id: "t2" });
  expect(p).toEqual({ job_ids: ["j1"], new_tech_id: "t2" });
  expect("new_crew_id" in p).toBe(false);
});

it("U4 · empty crews degrades to the pre-UU tech-only list; both empty → 'No technicians available'", () => {
  const a = mount({ crews: [] });
  expect(a.q.queryByTestId("reassign-crew-c1")).toBeNull();
  expect(a.q.getByTestId("reassign-tech-t1")).toBeTruthy();
  expect(a.q.queryByTestId("reassign-empty")).toBeNull();
  a.q.unmount();
  const b = mount({ crews: undefined, techs: [] });
  expect(b.q.getByTestId("reassign-empty").props.children).toBe("No technicians available");
  b.q.unmount();
  const c = mount({ techs: [] }); // crews only → no empty text
  expect(c.q.queryByTestId("reassign-empty")).toBeNull();
});

it("U5 · selected state reflects the picked entry only", () => {
  const { q } = mount({ pickedCrewId: "c1" });
  expect(q.getByTestId("reassign-crew-c1").props.accessibilityState).toEqual({ selected: true });
  expect(q.getByTestId("reassign-tech-t1").props.accessibilityState).toEqual({ selected: false });
  expect(reassignRoleLabel(null)).toBe("");
});

it("U6 · calendar wiring: crews from the existing GET /crews; exclusive picks; crew → new_crew_id; confirm enabled by either pick", () => {
  expect(SRC).toContain('api.get("/crews")');
  expect(SRC).toContain('const [reassignCrewId, setReassignCrewId] = useState(""); // UU-mobile');
  expect(SRC).toContain('onPickTech={(id) => { setReassignTechId(id); setReassignCrewId(""); }}');
  expect(SRC).toContain('onPickCrew={(id) => { setReassignCrewId(id); setReassignTechId(""); }}');
  expect(SRC).toContain('const pick: ReassignPick = reassignCrewId ? { kind: "crew", id: reassignCrewId } : { kind: "tech", id: reassignTechId };');
  expect(SRC).toContain("disabled={!(reassignTechId || reassignCrewId) || busy}");
  expect(SRC).toContain('(crews.find((c: any) => c.id === reassignCrewId)?.name || "crew")');
  expect(SRC).not.toContain("techs.map((t) => (\n                <Pressable"); // inline tech list replaced by ReassignPickerList
});
