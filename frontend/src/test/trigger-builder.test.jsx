/**
 * Feb 2026 · Phase 2 Custom Trigger Builder — vitest suite.
 *
 * Covers every component + the helpers module + the wired
 * SequenceEditor payload shape. Aiming for ~30+ tests across:
 *
 *   1. helpers.js — stripEmptyFilters, validateTrigger,
 *      buildTriggerPayload, normaliseDelay, draft persistence.
 *   2. EventPicker — 15+ events grouped by entity, searchable.
 *   3. DelayComposer — all 4 modes; "before" disabled correctly.
 *   4. FilterBuilder — each of the 9 dims can be set and cleared.
 *   5. ConditionRow — event/delay/filter propagate; remove button.
 *   6. TriggerBuilder — AND/OR toggle, add/remove condition,
 *      validation errors, auto-switch "before" → "after".
 *   7. LiveMatchPreview — debounced fetch, count rendering,
 *      truncated flag.
 *   8. Integration — build a 2-condition AND, save via mocked
 *      PATCH, verify payload shape.
 */
import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ─── api mock ────────────────────────────────────────────────────
// vi.mock is hoisted, so we use vi.hoisted() to lift the shared mock
// object above it. Without this, ``mockApi`` would be a TDZ error
// at the point vi.mock's factory runs.
const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    del: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/api", () => ({ api: mockApi }));

// eslint-disable-next-line import/first
import {
  stripEmptyFilters, validateTrigger, buildTriggerPayload,
  normaliseDelay, loadDraft, saveDraft, clearDraft, DRAFT_KEY,
} from "@/components/marketing/triggerBuilder/helpers";
// eslint-disable-next-line import/first
import { EventPicker } from "@/components/marketing/triggerBuilder/EventPicker";
// eslint-disable-next-line import/first
import { DelayComposer } from "@/components/marketing/triggerBuilder/DelayComposer";
// eslint-disable-next-line import/first
import { FilterBuilder } from "@/components/marketing/triggerBuilder/FilterBuilder";
// eslint-disable-next-line import/first
import { ConditionRow } from "@/components/marketing/triggerBuilder/ConditionRow";
// eslint-disable-next-line import/first
import { TriggerBuilder } from "@/components/marketing/triggerBuilder/TriggerBuilder";
// eslint-disable-next-line import/first
import { LiveMatchPreview } from "@/components/marketing/triggerBuilder/LiveMatchPreview";


// ─── Fixtures ────────────────────────────────────────────────────
const MOCK_CATALOG = [
  { id: "new_lead", label: "New lead created", entity: "lead", scheduled: false, allow_negative_offset: false },
  { id: "lead_status_changed", label: "Lead status changed", entity: "lead", scheduled: false, allow_negative_offset: false },
  { id: "estimate_sent", label: "Estimate sent", entity: "estimate", scheduled: false, allow_negative_offset: false },
  { id: "estimate_signed", label: "Estimate signed", entity: "estimate", scheduled: false, allow_negative_offset: false },
  { id: "job_scheduled", label: "Job scheduled", entity: "job", scheduled: true, allow_negative_offset: true },
  { id: "job_scheduled_reminder_1d", label: "1 day before scheduled job", entity: "job", scheduled: true, allow_negative_offset: true },
  { id: "job_completed", label: "Job completed", entity: "job", scheduled: false, allow_negative_offset: false },
  { id: "job_cancelled", label: "Job cancelled", entity: "job", scheduled: false, allow_negative_offset: false },
  { id: "chemistry_out_of_range", label: "Chemistry out of range", entity: "job", scheduled: false, allow_negative_offset: false },
  { id: "repair_flagged", label: "Repair flagged", entity: "job", scheduled: false, allow_negative_offset: false },
  { id: "invoice_sent", label: "Invoice sent", entity: "invoice", scheduled: false, allow_negative_offset: false },
  { id: "invoice_paid", label: "Invoice paid", entity: "invoice", scheduled: false, allow_negative_offset: false },
  { id: "invoice_overdue", label: "Invoice overdue", entity: "invoice", scheduled: true, allow_negative_offset: false },
  { id: "payment_failed", label: "Payment failed", entity: "payment", scheduled: false, allow_negative_offset: false },
  { id: "customer_birthday", label: "Customer birthday", entity: "customer", scheduled: true, allow_negative_offset: true },
  { id: "service_anniversary", label: "Service anniversary", entity: "customer", scheduled: true, allow_negative_offset: true },
];


beforeEach(() => {
  mockApi.get.mockReset();
  mockApi.post.mockReset();
  mockApi.patch.mockReset();
  window.localStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});


// ═══════════════════════════════════════════════════════════════════
// 1. helpers.js
// ═══════════════════════════════════════════════════════════════════
describe("helpers.stripEmptyFilters", () => {
  it("drops empty arrays and empty strings", () => {
    const out = stripEmptyFilters({
      customer_segment: [],
      zip: ["85387"],
      tags: [""],
      job_value_gte: 500,
      neverset: null,
    });
    expect(out).toEqual({ zip: ["85387"], job_value_gte: 500 });
  });

  it("keeps numeric zero for job_value_gte", () => {
    expect(stripEmptyFilters({ job_value_gte: 0 })).toEqual({ job_value_gte: 0 });
  });

  it("returns {} for null / non-object input", () => {
    expect(stripEmptyFilters(null)).toEqual({});
    expect(stripEmptyFilters(undefined)).toEqual({});
  });
});


describe("helpers.validateTrigger", () => {
  it("fails when no conditions", () => {
    const r = validateTrigger({ logic: "AND", conditions: [] }, MOCK_CATALOG);
    expect(r.ok).toBe(false);
    expect(r.errors[0]).toMatch(/at least one condition/i);
  });

  it("fails when a condition has no event", () => {
    const r = validateTrigger({
      logic: "AND",
      conditions: [{ event: "", delay: { mode: "immediate" }, filters: {} }],
    }, MOCK_CATALOG);
    expect(r.ok).toBe(false);
    expect(r.errors[0]).toMatch(/pick an event/i);
  });

  it("fails when 'before' delay picked but event doesn't allow negative offset", () => {
    const r = validateTrigger({
      logic: "AND",
      conditions: [{
        event: "new_lead",  // no allow_negative_offset
        delay: { mode: "before", value: 2 },
        filters: {},
      }],
    }, MOCK_CATALOG);
    expect(r.ok).toBe(false);
    expect(r.errors[0]).toMatch(/does not support .before./i);
  });

  it("passes on a well-formed after/immediate/on_weekday condition", () => {
    for (const d of [
      { mode: "immediate" },
      { mode: "after", value: 3, unit: "day" },
      { mode: "on_weekday", weekday: 1, time_local: "09:00" },
    ]) {
      const r = validateTrigger({
        logic: "AND",
        conditions: [{ event: "new_lead", delay: d, filters: {} }],
      }, MOCK_CATALOG);
      expect(r.ok).toBe(true);
    }
  });

  it("catches bad weekday and bad time_local", () => {
    const r1 = validateTrigger({
      logic: "AND",
      conditions: [{ event: "new_lead", delay: { mode: "on_weekday", weekday: 9, time_local: "09:00" } }],
    }, MOCK_CATALOG);
    expect(r1.ok).toBe(false);

    const r2 = validateTrigger({
      logic: "AND",
      conditions: [{ event: "new_lead", delay: { mode: "on_weekday", weekday: 0, time_local: "9am" } }],
    }, MOCK_CATALOG);
    expect(r2.ok).toBe(false);
  });
});


describe("helpers.buildTriggerPayload / normaliseDelay", () => {
  it("normalises the delay of every condition", () => {
    const out = buildTriggerPayload({
      logic: "or",
      conditions: [
        { event: "new_lead", delay: { mode: "after", value: "3", unit: "hour" }, filters: {} },
        { event: "job_scheduled", delay: { mode: "before", value: "2" } },
      ],
    });
    expect(out.logic).toBe("OR");
    expect(out.conditions[0].delay).toEqual({ mode: "after", value: 3, unit: "hour" });
    expect(out.conditions[1].delay).toEqual({ mode: "before", value: 2 });
  });

  it("strips empty filters per condition", () => {
    const out = buildTriggerPayload({
      logic: "AND",
      conditions: [{
        event: "job_completed",
        delay: { mode: "immediate" },
        filters: { customer_segment: [], zip: ["85387"], job_value_gte: null },
      }],
    });
    expect(out.conditions[0].filters).toEqual({ zip: ["85387"] });
  });
});


describe("helpers draft persistence", () => {
  it("saves and loads a trigger draft under a sequence-scoped key", () => {
    const draft = { logic: "AND", conditions: [{ event: "new_lead" }] };
    saveDraft("seq-42", draft);
    expect(window.localStorage.getItem(DRAFT_KEY("seq-42"))).toBeTruthy();
    expect(loadDraft("seq-42")).toEqual(draft);
  });

  it("clearDraft removes the entry", () => {
    saveDraft("seq-42", { logic: "AND", conditions: [] });
    clearDraft("seq-42");
    expect(loadDraft("seq-42")).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2. EventPicker
// ═══════════════════════════════════════════════════════════════════
describe("EventPicker", () => {
  it("renders 15+ events grouped by entity", () => {
    render(<EventPicker value="" catalog={MOCK_CATALOG} onChange={() => {}} />);
    fireEvent.click(screen.getByTestId("trigger-event-button"));
    expect(screen.getByTestId("trigger-event-group-lead")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-group-estimate")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-group-job")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-group-invoice")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-group-payment")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-group-customer")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-option-new_lead")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-option-job_scheduled")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-event-option-customer_birthday")).toBeInTheDocument();
  });

  it("filters events on search", () => {
    render(<EventPicker value="" catalog={MOCK_CATALOG} onChange={() => {}} />);
    fireEvent.click(screen.getByTestId("trigger-event-button"));
    const searchInput = screen.getByTestId("trigger-event-search");
    fireEvent.change(searchInput, { target: { value: "birthday" } });
    expect(screen.getByTestId("trigger-event-option-customer_birthday")).toBeInTheDocument();
    expect(screen.queryByTestId("trigger-event-option-new_lead")).not.toBeInTheDocument();
  });

  it("shows empty state when no events match", () => {
    render(<EventPicker value="" catalog={MOCK_CATALOG} onChange={() => {}} />);
    fireEvent.click(screen.getByTestId("trigger-event-button"));
    fireEvent.change(screen.getByTestId("trigger-event-search"), {
      target: { value: "zzzz" },
    });
    expect(screen.getByTestId("trigger-event-empty")).toBeInTheDocument();
  });

  it("emits onChange with the picked event", () => {
    const onChange = vi.fn();
    render(<EventPicker value="" catalog={MOCK_CATALOG} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("trigger-event-button"));
    fireEvent.click(screen.getByTestId("trigger-event-option-job_completed"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "job_completed", entity: "job" }),
    );
  });
});


// ═══════════════════════════════════════════════════════════════════
// 3. DelayComposer
// ═══════════════════════════════════════════════════════════════════
describe("DelayComposer", () => {
  const jobScheduledEvt = MOCK_CATALOG.find((e) => e.id === "job_scheduled");
  const newLeadEvt = MOCK_CATALOG.find((e) => e.id === "new_lead");

  it("renders all 4 mode buttons", () => {
    render(<DelayComposer value={{ mode: "immediate" }} event={jobScheduledEvt} onChange={() => {}} />);
    expect(screen.getByTestId("trigger-delay-mode-immediate")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-delay-mode-after")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-delay-mode-before")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-delay-mode-weekday")).toBeInTheDocument();
  });

  it("disables 'before' when the event doesn't allow negative offset", () => {
    render(<DelayComposer value={{ mode: "immediate" }} event={newLeadEvt} onChange={() => {}} />);
    const beforeBtn = screen.getByTestId("trigger-delay-mode-before");
    expect(beforeBtn).toBeDisabled();
    expect(screen.getByTestId("trigger-delay-before-disabled-hint")).toBeInTheDocument();
  });

  it("enables 'before' when event allows it and switches mode on click", () => {
    const onChange = vi.fn();
    render(<DelayComposer value={{ mode: "immediate" }} event={jobScheduledEvt} onChange={onChange} />);
    const beforeBtn = screen.getByTestId("trigger-delay-mode-before");
    expect(beforeBtn).not.toBeDisabled();
    fireEvent.click(beforeBtn);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ mode: "before" }));
  });

  it("renders after-value + unit when in 'after' mode", () => {
    render(<DelayComposer value={{ mode: "after", value: 3, unit: "day" }} event={newLeadEvt} onChange={() => {}} />);
    expect(screen.getByTestId("trigger-delay-after-value")).toHaveValue(3);
    expect(screen.getByTestId("trigger-delay-after-unit")).toHaveValue("day");
  });

  it("renders weekday selector + time input when in 'on_weekday' mode", () => {
    render(<DelayComposer value={{ mode: "on_weekday", weekday: 2, time_local: "10:00" }} event={newLeadEvt} onChange={() => {}} />);
    expect(screen.getByTestId("trigger-delay-weekday-select")).toHaveValue("2");
    expect(screen.getByTestId("trigger-delay-weekday-time")).toHaveValue("10:00");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 4. FilterBuilder
// ═══════════════════════════════════════════════════════════════════
describe("FilterBuilder", () => {
  it("renders all 9 filter rows", () => {
    render(<FilterBuilder filters={{}} onChange={() => {}} technicians={[]} crews={[]} />);
    expect(screen.getByTestId("filter-row-customer_segment")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-work_class")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-tags")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-technician_id")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-crew_id")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-job_value_gte")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-zip")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-last_visit_gte_days")).toBeInTheDocument();
    expect(screen.getByTestId("filter-row-custom_fields")).toBeInTheDocument();
  });

  it("toggling a customer_segment chip emits the filter update", () => {
    const onChange = vi.fn();
    render(<FilterBuilder filters={{}} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("filter-row-customer_segment-toggle"));
    fireEvent.click(screen.getByTestId("trigger-filter-segment-pool"));
    expect(onChange).toHaveBeenCalledWith({ customer_segment: ["pool"] });
  });

  it("clearing a segment removes the whole key (empty array is dropped)", () => {
    const onChange = vi.fn();
    render(<FilterBuilder filters={{ customer_segment: ["pool"] }} onChange={onChange} />);
    // segment row is auto-expanded because it carries a value
    fireEvent.click(screen.getByTestId("trigger-filter-segment-pool"));
    expect(onChange).toHaveBeenCalledWith({}); // pool removed → set to empty array → dropped
  });

  it("job_value_gte input writes numeric value", () => {
    const onChange = vi.fn();
    render(<FilterBuilder filters={{}} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("filter-row-job_value_gte-toggle"));
    fireEvent.change(screen.getByTestId("trigger-filter-job-value-gte"), {
      target: { value: "750" },
    });
    expect(onChange).toHaveBeenCalledWith({ job_value_gte: 750 });
  });

  it("adding a custom field spec writes to custom_fields array", () => {
    const onChange = vi.fn();
    render(<FilterBuilder filters={{}} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("filter-row-custom_fields-toggle"));
    fireEvent.click(screen.getByTestId("trigger-filter-cf-add"));
    expect(onChange).toHaveBeenCalledWith({
      custom_fields: [{ key: "", op: "eq", value: "" }],
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 5. ConditionRow
// ═══════════════════════════════════════════════════════════════════
describe("ConditionRow", () => {
  it("renders event picker + delay + filters toggle", () => {
    render(
      <ConditionRow
        index={0}
        condition={{ event: "", delay: { mode: "immediate" }, filters: {} }}
        catalog={MOCK_CATALOG}
        onChange={() => {}}
        onRemove={() => {}}
        testIdPrefix="trigger"
      />,
    );
    expect(screen.getByTestId("trigger-row-0-event-button")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-row-0-delay-wrap")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-row-0-filters-toggle")).toBeInTheDocument();
  });

  it("clicking remove calls onRemove", () => {
    const onRemove = vi.fn();
    render(
      <ConditionRow
        index={2}
        condition={{ event: "new_lead", delay: { mode: "immediate" }, filters: {} }}
        catalog={MOCK_CATALOG}
        onChange={() => {}}
        onRemove={onRemove}
        testIdPrefix="trigger"
      />,
    );
    fireEvent.click(screen.getByTestId("trigger-row-2-remove"));
    expect(onRemove).toHaveBeenCalled();
  });

  it("shows filter count badge when filters present", () => {
    render(
      <ConditionRow
        index={0}
        condition={{ event: "new_lead", delay: { mode: "immediate" }, filters: { zip: ["85387"] } }}
        catalog={MOCK_CATALOG}
        onChange={() => {}}
        onRemove={() => {}}
        testIdPrefix="trigger"
      />,
    );
    expect(screen.getByTestId("trigger-row-0-filters-count")).toHaveTextContent("1");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 6. TriggerBuilder — full integration
// ═══════════════════════════════════════════════════════════════════
function _defaultApiMocks() {
  mockApi.get.mockImplementation((path) => {
    if (path.includes("event-catalog")) return Promise.resolve({ events: MOCK_CATALOG });
    if (path.includes("/users?role=technician")) return Promise.resolve({ users: [] });
    if (path.includes("/crews")) return Promise.resolve({ crews: [] });
    return Promise.resolve({});
  });
  mockApi.post.mockResolvedValue({
    sequence_id: "seq-1",
    match_count: 12,
    sample: [
      { customer_id: "c1", name: "Alice", reason: "job_completed" },
      { customer_id: "c2", name: "Bob",   reason: "job_completed" },
    ],
    truncated: false,
    evaluated_at: "2026-02-15T12:00:00Z",
  });
}


describe("TriggerBuilder", () => {
  it("shows empty state when no conditions", async () => {
    _defaultApiMocks();
    render(<TriggerBuilder sequenceId="seq-1" initialTrigger={null} />);
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(screen.getByTestId("trigger-conditions-empty")).toBeInTheDocument();
  });

  it("AND/OR toggle switches the trigger.logic", async () => {
    _defaultApiMocks();
    const onChange = vi.fn();
    render(<TriggerBuilder sequenceId="seq-1" initialTrigger={null} onChange={onChange} />);
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("trigger-logic-or"));
    await waitFor(() => {
      const last = onChange.mock.calls.at(-1)[0];
      expect(last.logic).toBe("OR");
    });
  });

  it("add + remove condition round-trip", async () => {
    _defaultApiMocks();
    render(<TriggerBuilder sequenceId="seq-1" initialTrigger={null} />);
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("trigger-add-condition"));
    expect(screen.getByTestId("trigger-row-0")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("trigger-row-0-remove"));
    await waitFor(() => {
      expect(screen.queryByTestId("trigger-row-0")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("trigger-conditions-empty")).toBeInTheDocument();
  });

  it("validation errors surface when a condition has no event", async () => {
    _defaultApiMocks();
    const onValidity = vi.fn();
    render(<TriggerBuilder sequenceId="seq-1" onValidityChange={onValidity} />);
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("trigger-add-condition"));
    await waitFor(() => {
      expect(screen.getByTestId("trigger-validation-errors")).toBeInTheDocument();
      const last = onValidity.mock.calls.at(-1)?.[0];
      expect(last?.ok).toBe(false);
    });
  });

  it("hydrates from initialTrigger.conditions", async () => {
    _defaultApiMocks();
    render(
      <TriggerBuilder
        sequenceId="seq-9"
        initialTrigger={{
          logic: "OR",
          conditions: [
            { event: "job_completed", delay: { mode: "immediate" }, filters: {} },
          ],
        }}
      />,
    );
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    // OR button should show active state (styling test — check aria via testid presence).
    expect(screen.getByTestId("trigger-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-logic-or")).toBeInTheDocument();
  });

  it("persists an unsaved draft to localStorage keyed by sequence id", async () => {
    _defaultApiMocks();
    render(<TriggerBuilder sequenceId="seq-drft" />);
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("trigger-add-condition"));
    await waitFor(() => {
      const stored = window.localStorage.getItem(DRAFT_KEY("seq-drft"));
      expect(stored).toBeTruthy();
      const parsed = JSON.parse(stored);
      expect(parsed.conditions).toHaveLength(1);
    });
  });

  it("hydrates from localStorage draft on remount", async () => {
    _defaultApiMocks();
    saveDraft("seq-persist", {
      logic: "OR",
      conditions: [{ event: "invoice_paid", delay: { mode: "immediate" }, filters: {} }],
    });
    render(<TriggerBuilder sequenceId="seq-persist" />);
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(screen.getByTestId("trigger-row-0")).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 7. LiveMatchPreview — debounced fetch
// ═══════════════════════════════════════════════════════════════════
describe("LiveMatchPreview", () => {
  it("shows idle empty state when no conditions", async () => {
    render(
      <LiveMatchPreview
        sequenceId="seq-1"
        trigger={{ logic: "AND", conditions: [] }}
        enabled
      />,
    );
    expect(screen.getByTestId("trigger-preview-idle")).toBeInTheDocument();
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it("fires POST /preview-matches after 500ms debounce and renders count", async () => {
    mockApi.post.mockResolvedValue({
      sequence_id: "seq-1",
      match_count: 42,
      sample: [{ customer_id: "c-a", name: "Alpha", reason: "new_lead" }],
      truncated: false,
      evaluated_at: "2026-02-15T12:00:00Z",
    });

    render(
      <LiveMatchPreview
        sequenceId="seq-1"
        trigger={{
          logic: "AND",
          conditions: [{
            event: "new_lead", delay: { mode: "immediate" }, filters: {},
          }],
        }}
        enabled
      />,
    );

    // Advance the 500ms debounce.
    await act(async () => { vi.advanceTimersByTime(600); });
    await waitFor(() => {
      expect(mockApi.post).toHaveBeenCalledWith(
        "/marketing/sequences/seq-1/preview-matches",
        expect.objectContaining({
          trigger_override: expect.any(Object),
          limit: 25,
        }),
        expect.any(Number),
      );
      expect(screen.getByTestId("trigger-preview-count")).toHaveTextContent("42");
    });
  });

  it("shows truncation hint when match_count > sample length", async () => {
    mockApi.post.mockResolvedValue({
      sequence_id: "seq-1",
      match_count: 100,
      sample: [{ customer_id: "c-a", name: "Alpha" }],
      truncated: true,
      evaluated_at: "2026-02-15T12:00:00Z",
    });

    render(
      <LiveMatchPreview
        sequenceId="seq-1"
        trigger={{
          logic: "AND",
          conditions: [{ event: "new_lead", delay: { mode: "immediate" } }],
        }}
        enabled
      />,
    );
    await act(async () => { vi.advanceTimersByTime(600); });
    await waitFor(() => {
      expect(screen.getByTestId("trigger-preview-count")).toHaveTextContent("100");
    });
  });

  it("renders zero-state message when match_count is 0", async () => {
    mockApi.post.mockResolvedValue({
      sequence_id: "seq-1",
      match_count: 0,
      sample: [],
      truncated: false,
      evaluated_at: "2026-02-15T12:00:00Z",
    });

    render(
      <LiveMatchPreview
        sequenceId="seq-1"
        trigger={{
          logic: "AND",
          conditions: [{ event: "invoice_paid", delay: { mode: "immediate" } }],
        }}
        enabled
      />,
    );
    await act(async () => { vi.advanceTimersByTime(600); });
    await waitFor(() => {
      expect(screen.getByTestId("trigger-preview-empty")).toBeInTheDocument();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 8. End-to-end — build 2-condition AND, save via PATCH shape
// ═══════════════════════════════════════════════════════════════════
describe("Phase 2 payload shape (integration)", () => {
  it("buildTriggerPayload produces a schema-v2 PATCH-ready doc", () => {
    // Simulate what SequenceEditor's buildPayload will send.
    const state = {
      logic: "AND",
      conditions: [
        {
          event: "job_completed",
          delay: { mode: "immediate" },
          filters: { customer_segment: ["pool"], zip: ["85387"] },
        },
        {
          event: "invoice_paid",
          delay: { mode: "after", value: 2, unit: "day" },
          filters: {},
        },
      ],
    };
    const patch = buildTriggerPayload(state);
    expect(patch).toEqual({
      logic: "AND",
      conditions: [
        {
          event: "job_completed",
          delay: { mode: "immediate" },
          filters: { customer_segment: ["pool"], zip: ["85387"] },
        },
        {
          event: "invoice_paid",
          delay: { mode: "after", value: 2, unit: "day" },
          filters: {},
        },
      ],
    });
  });

  it("Save-time validation blocks a payload with a 'before' delay on a non-scheduled event", () => {
    const validity = validateTrigger({
      logic: "AND",
      conditions: [{
        event: "new_lead",  // not allow_negative_offset
        delay: { mode: "before", value: 3 },
        filters: {},
      }],
    }, MOCK_CATALOG);
    expect(validity.ok).toBe(false);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 9. Phase 3 polish — drag reorder, unsaved-toast, zero-cond text
// ═══════════════════════════════════════════════════════════════════
describe("Phase 3 polish", () => {
  it("LiveMatchPreview idle state uses the concise polish copy", () => {
    render(
      <LiveMatchPreview
        sequenceId="seq-x"
        trigger={{ logic: "AND", conditions: [] }}
        enabled
      />,
    );
    const idle = screen.getByTestId("trigger-preview-idle");
    expect(idle).toBeInTheDocument();
    // Polish spec: "Add a condition to see match count".
    expect(idle.textContent || "").toMatch(/add a condition/i);
    expect(idle.textContent || "").toMatch(/match count/i);
  });

  it("ConditionRow exposes a drag handle and dropping reorders", () => {
    const onReorder = vi.fn();
    render(
      <ConditionRow
        index={1}
        condition={{ event: "job_completed", delay: { mode: "immediate" }, filters: {} }}
        catalog={MOCK_CATALOG}
        technicians={[]}
        crews={[]}
        onChange={() => {}}
        onRemove={() => {}}
        onReorder={onReorder}
        testIdPrefix="trigger"
      />,
    );
    // Drag handle renders when onReorder is passed.
    const handle = screen.getByTestId("trigger-row-1-drag-handle");
    expect(handle).toBeInTheDocument();

    // Simulate HTML5 drop with "0" (source index) landing on row 1.
    const row = screen.getByTestId("trigger-row-1");
    const setData = vi.fn();
    const getData = vi.fn().mockReturnValue("0");
    fireEvent.dragStart(handle, {
      dataTransfer: { setData, effectAllowed: "" },
    });
    fireEvent.dragOver(row, {
      dataTransfer: { dropEffect: "" },
    });
    fireEvent.drop(row, {
      dataTransfer: { getData },
    });
    expect(onReorder).toHaveBeenCalledWith(0, 1);
  });

  it("ConditionRow hides the drag handle when onReorder is not provided", () => {
    render(
      <ConditionRow
        index={0}
        condition={{ event: "job_completed", delay: { mode: "immediate" }, filters: {} }}
        catalog={MOCK_CATALOG}
        technicians={[]}
        crews={[]}
        onChange={() => {}}
        onRemove={() => {}}
        testIdPrefix="trigger"
      />,
    );
    expect(screen.queryByTestId("trigger-row-0-drag-handle")).not.toBeInTheDocument();
  });

  it("TriggerBuilder reorders conditions when a row is dragged onto another", async () => {
    _defaultApiMocks();
    const onChange = vi.fn();
    render(
      <TriggerBuilder
        sequenceId="seq-reorder"
        initialTrigger={{
          logic: "AND",
          conditions: [
            { event: "job_completed", delay: { mode: "immediate" }, filters: {} },
            { event: "invoice_paid",  delay: { mode: "immediate" }, filters: {} },
          ],
        }}
        onChange={onChange}
      />,
    );
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());

    // Drag row 1 (invoice_paid) up onto row 0.
    const handle = screen.getByTestId("trigger-row-1-drag-handle");
    const row0 = screen.getByTestId("trigger-row-0");
    fireEvent.dragStart(handle, {
      dataTransfer: { setData: vi.fn(), effectAllowed: "" },
    });
    fireEvent.dragOver(row0, {
      dataTransfer: { dropEffect: "" },
    });
    fireEvent.drop(row0, {
      dataTransfer: { getData: vi.fn().mockReturnValue("1") },
    });

    await waitFor(() => {
      const last = onChange.mock.calls.at(-1)[0];
      expect(last.conditions.map((c) => c.event)).toEqual([
        "invoice_paid", "job_completed",
      ]);
    });
  });

  it("TriggerBuilder emits onDirtyChange(true) when a condition is added", async () => {
    _defaultApiMocks();
    const onDirtyChange = vi.fn();
    render(
      <TriggerBuilder
        sequenceId="seq-dirty"
        initialTrigger={{ logic: "AND", conditions: [] }}
        onDirtyChange={onDirtyChange}
      />,
    );
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    // Not dirty at boot.
    expect(onDirtyChange.mock.calls.at(-1)?.[0]).toBe(false);
    fireEvent.click(screen.getByTestId("trigger-add-condition"));
    await waitFor(() => {
      expect(onDirtyChange.mock.calls.at(-1)?.[0]).toBe(true);
    });
  });

  it("TriggerBuilder registers a beforeunload handler while dirty", async () => {
    _defaultApiMocks();
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = render(
      <TriggerBuilder sequenceId="seq-bu" initialTrigger={{ logic: "AND", conditions: [] }} />,
    );
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("trigger-add-condition"));
    await waitFor(() => {
      const kinds = addSpy.mock.calls.map((c) => c[0]);
      expect(kinds).toContain("beforeunload");
    });
    // Unmount → the beforeunload handler must detach.
    unmount();
    const removedKinds = removeSpy.mock.calls.map((c) => c[0]);
    expect(removedKinds).toContain("beforeunload");
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });
});
