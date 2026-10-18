/**
 * TD-73 (web 73ac7cc3f) — portal Edit Profile Save recoloured to the
 * Call Now green #16A34A. Mobile has no hero Edit-profile pill / modal;
 * its parallel is the full-page `portal/profile.tsx` editor, whose
 * inputs already match the web modal retheme on bg + border (white bg,
 * #E4E4E7 border). Input TEXT stays navy #000080 by design: every mobile
 * input goes through `AppTextInput` (Phase T1 sitewide theme — white bg /
 * navy text, applied last so it always wins). Web modal uses #0F172A;
 * matching it would mean changing the sitewide primitive (out of scope —
 * operator-confirmed default (a), see memory/mobile_parity_catchup_audit.md).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { StyleSheet } from "react-native";
import { render } from "@testing-library/react-native";

import { PrimaryButton } from "@/src/components/ui";
import { Field } from "@/app/customer/new";
import { colors, inputColors } from "@/src/theme";

jest.mock("react-native-keyboard-controller", () => {
  const { ScrollView } = jest.requireActual("react-native");
  return { KeyboardAwareScrollView: ScrollView, KeyboardProvider: ({ children }: any) => children };
});

const src = fs.readFileSync(path.join(__dirname, "../app/portal/profile.tsx"), "utf8");

it("profile Save uses the success (Call Now green) variant", () => {
  const line = src.split("\n").find((l) => l.includes('testID="portal-profile-save"')) || "";
  expect(line).toContain('variant="success"');
  expect(colors.success).toBe("#16A34A");
});

it("success PrimaryButton renders #16A34A with white label", () => {
  const q = render(<PrimaryButton title="Save Changes" onPress={() => {}} variant="success" testID="btn" />);
  const bgs = q.UNSAFE_root.findAll((n: any) => StyleSheet.flatten(n.props?.style)?.backgroundColor === "#16A34A");
  expect(bgs.length).toBeGreaterThan(0);
  expect(StyleSheet.flatten(q.getByText("Save Changes").props.style).color).toBe("#FFFFFF");
});

it("profile inputs: white bg + light-grey border (web parity); text = sitewide T1 navy", () => {
  const q = render(<Field label="Full Name" value="" onChangeText={() => {}} testID="f" />);
  const st = StyleSheet.flatten(q.getByTestId("f").props.style);
  expect(st).toMatchObject({ backgroundColor: "#FFFFFF", borderColor: "#E4E4E7", color: "#000080" });
  expect(inputColors.text).toBe("#000080");
});
