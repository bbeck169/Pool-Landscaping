/**
 * iOS decimal entry for chemistry readings.
 *
 * iOS `decimal-pad` emits the locale decimal separator ("," on many
 * locales). Every chemistry entry surface now routes keystrokes through
 * `sanitizeDecimalInput` so "7,6" → "7.6", a 2nd dot / junk is ignored,
 * and partials ("7.") survive until commit.
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { Platform } from "react-native";
import { render, fireEvent } from "@testing-library/react-native";

import ReadingChipRow from "@/src/components/checklist/ReadingChipRow";
import { sanitizeDecimalInput } from "@/src/utils/decimalInput";

const setup = (value: number | null = null, key = "ph") => {
  const onChange = jest.fn();
  const q = render(<ReadingChipRow readingKey={key} label="pH" value={value} onChange={onChange} />);
  const input = () => q.getByTestId(`pool-reading-${key}-input`);
  return { q, onChange, input };
};

describe("sanitizeDecimalInput", () => {
  it("normalises the iOS locale comma and strips whitespace", () => {
    expect(sanitizeDecimalInput("7,6")).toBe("7.6");
    expect(sanitizeDecimalInput(" 0,5 ")).toBe("0.5");
  });
  it("passes valid partials through", () => {
    expect(sanitizeDecimalInput("7.")).toBe("7.");
    expect(sanitizeDecimalInput(".5")).toBe(".5");
    expect(sanitizeDecimalInput("")).toBe("");
  });
  it("rejects a second decimal point (keeps previous)", () => {
    expect(sanitizeDecimalInput("7.6.5", "7.6")).toBe("7.6");
    expect(sanitizeDecimalInput("7,6.", "7.6")).toBe("7.6");
  });
  it("rejects junk (letters, minus, exponent) as a no-op", () => {
    expect(sanitizeDecimalInput("abc", "")).toBe("");
    expect(sanitizeDecimalInput("7.6a", "7.6")).toBe("7.6");
    expect(sanitizeDecimalInput("-1", "")).toBe("");
    expect(sanitizeDecimalInput("1e3", "1")).toBe("1");
  });
});

describe.each(["ios", "android"] as const)("ReadingChipRow pH on %s", (os) => {
  const original = Platform.OS;
  beforeAll(() => { (Platform as any).OS = os; });
  afterAll(() => { (Platform as any).OS = original; });

  it("uses decimal-pad", () => {
    const { input } = setup();
    expect(input().props.keyboardType).toBe("decimal-pad");
  });

  it("7.6 → stored as 7.6 → displayed as 7.6", () => {
    const { input, onChange } = setup();
    fireEvent.changeText(input(), "7.6");
    expect(input().props.value).toBe("7.6");
    fireEvent(input(), "blur");
    expect(onChange).toHaveBeenLastCalledWith(7.6);
  });

  it("iOS comma locale: 7,6 → 7.6", () => {
    const { input, onChange } = setup();
    fireEvent.changeText(input(), "7,6");
    expect(input().props.value).toBe("7.6");
    fireEvent(input(), "endEditing");
    expect(onChange).toHaveBeenLastCalledWith(7.6);
  });

  it("0.5 (chlorine) → stored + displayed", () => {
    const { input, onChange } = setup(null, "chlorine");
    fireEvent.changeText(input(), "0.5");
    expect(input().props.value).toBe("0.5");
    fireEvent(input(), "blur");
    expect(onChange).toHaveBeenLastCalledWith(0.5);
  });

  it("7. partial is allowed in-progress (no crash, no error) and commits as 7", () => {
    const { q, input, onChange } = setup();
    fireEvent.changeText(input(), "7.");
    expect(input().props.value).toBe("7.");
    expect(q.queryByTestId("pool-reading-ph-error")).toBeNull();
    fireEvent(input(), "blur");
    expect(onChange).toHaveBeenLastCalledWith(7);
  });

  it("7.6.5 → second decimal rejected (stays 7.6)", () => {
    const { input } = setup();
    fireEvent.changeText(input(), "7.6");
    fireEvent.changeText(input(), "7.6.5");
    expect(input().props.value).toBe("7.6");
  });

  it("abc → no-op", () => {
    const { input, onChange } = setup();
    fireEvent.changeText(input(), "abc");
    expect(input().props.value).toBe("");
    fireEvent(input(), "blur");
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("saved 7.6 hydrates as '7.6' (not 76 / 7 / NaN)", () => {
    const { input } = setup(7.6);
    expect(input().props.value).toBe("7.6");
  });

  it("range validation compares the parsed decimal (pH 14.5 invalid, 6.8 valid)", () => {
    const { q, input } = setup();
    fireEvent.changeText(input(), "14.5");
    expect(q.getByTestId("pool-reading-ph-error")).toBeTruthy();
    fireEvent.changeText(input(), "6.8");
    expect(q.queryByTestId("pool-reading-ph-error")).toBeNull();
  });
});

describe("other chemistry entry surfaces use the sanitizer + decimal-pad", () => {
  const read = (p: string) => fs.readFileSync(path.resolve(__dirname, "..", p), "utf-8");
  it("customer chemistry readings", () => {
    const SRC = read("app/customer/chemistry/[id].tsx");
    expect(SRC).toContain('sanitizeDecimalInput(v, prev[r.k] ?? "")');
    expect(SRC).toMatch(/sanitizeDecimalInput\(v, prev\[r\.k\] \?\? ""\) \}\)\)\}\s*\n\s*keyboardType="decimal-pad"/);
  });
  it("calculators NumInput", () => {
    const SRC = read("app/(app)/calculators.tsx");
    expect(SRC).toContain('onChangeText(sanitizeDecimalInput(t, value ?? ""))');
    expect(SRC).toMatch(/sanitizeDecimalInput\(t, value \?\? ""\)\)\}\s*\n\s*keyboardType="decimal-pad"/);
  });
});
