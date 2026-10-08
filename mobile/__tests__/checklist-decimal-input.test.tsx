/**
 * Mobile Job Checklist — decimal entry on chemistry readings.
 * Bug: WaterBodyPanel coerced every keystroke with Number(), so "7." → 7
 * (dot stripped) and "." → null (cleared). Fix: shared DecimalInput.
 */
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: "test-job" }),
  useFocusEffect: (cb: any) => cb(),
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "technician", id: "u1" } }), AuthProvider: ({ children }: any) => children }));

import React, { useState } from "react";
import { render, fireEvent } from "@testing-library/react-native";
import DecimalInput, { sanitizeDecimal, parseDecimal } from "@/src/components/common/DecimalInput";
import WaterBodyPanel from "@/src/components/checklist/WaterBodyPanel";
import { makeEmptyBody, READING_ALLOWLIST } from "@/src/lib/waterBodies";

function Harness({ onValue }: { onValue: jest.Mock }) {
  const [v, setV] = useState<number | null>(null);
  return <DecimalInput testID="dec" value={v} onChangeValue={(n) => { setV(n); onValue(n); }} />;
}

describe("DecimalInput (isolation)", () => {
  const setup = () => { const onValue = jest.fn(); const r = render(<Harness onValue={onValue} />); return { onValue, input: () => r.getByTestId("dec") }; };

  it("uses decimal-pad and keeps '7.' while typing", () => {
    const { input, onValue } = setup();
    expect(input().props.keyboardType).toBe("decimal-pad");
    fireEvent.changeText(input(), "7.");
    expect(input().props.value).toBe("7.");
    expect(onValue).toHaveBeenLastCalledWith(7);
  });

  it("'7.5' works end-to-end; '.' is an accepted intermediate state", () => {
    const { input, onValue } = setup();
    fireEvent.changeText(input(), ".");
    expect(input().props.value).toBe(".");
    expect(onValue).toHaveBeenLastCalledWith(null);
    fireEvent.changeText(input(), "7.5");
    expect(input().props.value).toBe("7.5");
    expect(onValue).toHaveBeenLastCalledWith(7.5);
  });

  it("rejects letters / second decimal point", () => {
    const { input, onValue } = setup();
    fireEvent.changeText(input(), "7.2");
    fireEvent.changeText(input(), "7.2a");
    fireEvent.changeText(input(), "7.2.");
    expect(input().props.value).toBe("7.2");
    expect(onValue).toHaveBeenCalledTimes(1);
  });

  it("blur: '7.' → 7 and '' → null", () => {
    const { input, onValue } = setup();
    fireEvent.changeText(input(), "7.");
    fireEvent(input(), "blur");
    expect(input().props.value).toBe("7");
    expect(onValue).toHaveBeenLastCalledWith(7);
    fireEvent.changeText(input(), "");
    fireEvent(input(), "blur");
    expect(onValue).toHaveBeenLastCalledWith(null);
    expect(input().props.value).toBe("");
  });

  it("helpers: comma → dot, '.' parses to null", () => {
    expect(sanitizeDecimal("7,5")).toBe("7.5");
    expect(sanitizeDecimal("abc")).toBeNull();
    expect(parseDecimal(".")).toBeNull();
    expect(parseDecimal(".5")).toBe(0.5);
  });
});

describe("WaterBodyPanel wiring (Job Checklist → Chemistry Readings)", () => {
  function Panel({ onBody }: { onBody: jest.Mock }) {
    const [body, setBody] = useState(makeEmptyBody("pool"));
    return <WaterBodyPanel body={body} index={0} locked={false} canRemove={false} isPrimary onChange={(b: any) => { setBody(b); onBody(b); }} onRemove={jest.fn()} />;
  }
  const reading = (b: any, key: string) => b.readings.find((r: any) => r.key === key)?.value;

  it("pH accepts '7.' then '7.5' and stores the number the submit flow reads", () => {
    const onBody = jest.fn();
    const r = render(<Panel onBody={onBody} />);
    const ph = () => r.getByTestId("reading-input-0-ph");
    fireEvent.changeText(ph(), "7.");
    expect(ph().props.value).toBe("7.");
    fireEvent.changeText(ph(), "7.5");
    expect(ph().props.value).toBe("7.5");
    expect(reading(onBody.mock.calls.at(-1)[0], "ph")).toBe(7.5);
  });

  it("every allowed pool reading renders as a decimal-safe input", () => {
    const r = render(<Panel onBody={jest.fn()} />);
    for (const key of READING_ALLOWLIST.pool) {
      const el = r.getByTestId(`reading-input-0-${key}`);
      fireEvent.changeText(el, "1.");
      expect(r.getByTestId(`reading-input-0-${key}`).props.value).toBe("1.");
    }
  });
});
