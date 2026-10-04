/**
 * APR-III · Feb-2026 — Alert Phone + Alert Email UI removed.
 *
 * Five assertions mapping to the APR-III brief:
 *
 *   a. CustomerDetail Overview tile row has no ``Alert phone`` /
 *      ``Alert email`` tile (and no leftover ``BellRing`` symbol
 *      inside the stat-tile array literal — the icon's only two
 *      consumers were the removed Alert tiles, so the import is
 *      trimmed and the file is free of the symbol).
 *   b. CustomerForm no longer renders ``data-testid="cf-alert-phone"``
 *      / ``cf-alert-email`` inputs.
 *   c. CustomerForm serialized submit payload cannot contain
 *      ``alert_phone`` / ``alert_email`` keys — the form state
 *      object no longer declares them and the submit path spreads
 *      the state via ``{...form, …}``.
 *   d. VisitRecapModal with a customer whose ``phone`` is empty but
 *      ``alert_phone`` is populated → SMS pill is DISABLED (hasPhone
 *      is false; alert_phone no longer acts as a fallback).
 *   e. VisitRecapModal with a customer whose ``phone`` is populated
 *      → SMS pill is NOT disabled.
 *
 * (a) / (b) / (c) proven source-level (matches the CP-1-B / GCR /
 * A2 / QF-1 pattern used across this repo — mounting CustomerDetail
 * / CustomerForm directly would need a mountain of mocks).  (d) /
 * (e) mount VisitRecapModal in isolation — it's a 243-line component
 * with only ``@/api`` + ``@/theme`` + ``lucide-react`` deps.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

import VisitRecapModal from "@/components/checklist/VisitRecapModal";

afterEach(cleanup);

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const CDET = read("src/pages/customers/CustomerDetail.jsx");
const CFORM = read("src/pages/customers/CustomerForm.jsx");
const CMOD = read("src/components/checklist/ChecklistModal.jsx");
const VMOD = read("src/components/checklist/VisitRecapModal.jsx");


/* ── (a) CustomerDetail — Alert tiles + BellRing symbol gone ───── */
describe("APR-III · (a) CustomerDetail Overview stat tiles", () => {
  it("has no ``Alert phone`` or ``Alert email`` tile entry", () => {
    expect(CDET).not.toMatch(/label: "Alert phone"/);
    expect(CDET).not.toMatch(/label: "Alert email"/);
    // No reads against the removed customer fields anywhere in the
    // page (CP-1-B / GCR already removed the lower <Info> render; now
    // the top-tile reads are gone too).
    expect(CDET).not.toMatch(/customer\.alert_phone/);
    expect(CDET).not.toMatch(/customer\.alert_email/);
  });

  it("the ``BellRing`` icon import + usages are removed (unused post-APR-III)", () => {
    // Zero hits of the BellRing symbol anywhere in the file — the
    // icon's only two consumers were the removed Alert tiles.
    expect(CDET).not.toMatch(/\bBellRing\b/);
  });
});


/* ── (b) CustomerForm — no cf-alert-phone / cf-alert-email inputs ─ */
describe("APR-III · (b) CustomerForm inputs", () => {
  it("renders no ``cf-alert-phone`` or ``cf-alert-email`` testid in source", () => {
    expect(CFORM).not.toMatch(/testid="cf-alert-phone"/);
    expect(CFORM).not.toMatch(/testid="cf-alert-email"/);
    // The <TextInput> label strings are gone too — defends against
    // a diff that strips the testid but leaves the <TextInput>.
    expect(CFORM).not.toMatch(/ALERT PHONE/);
    expect(CFORM).not.toMatch(/ALERT EMAIL/);
  });
});


/* ── (c) CustomerForm — submit payload cannot carry the keys ────── */
describe("APR-III · (c) CustomerForm serialized payload regression lock", () => {
  it("form state object no longer declares ``alert_phone`` / ``alert_email`` keys", () => {
    // Submit path is ``const doc = { ...form, … }`` → removing the
    // keys from the ``useState({...})`` initializer + the load path
    // guarantees they never land on ``doc``.  Zero substrings of
    // either key anywhere in the file enforces the invariant.
    expect(CFORM).not.toMatch(/alert_phone/);
    expect(CFORM).not.toMatch(/alert_email/);
    // Positive lock — the submit path shape is intact.
    expect(CFORM).toMatch(/const doc = \{\s*\.\.\.form,/);
  });

  it("ChecklistModal recap passthrough drops the ``alert_phone`` key", () => {
    expect(CMOD).not.toMatch(/alert_phone/);
    // Positive lock — the passthrough object still carries the four
    // kept keys (id / name / email / phone).
    expect(CMOD).toMatch(/setRecapCustomer\(\{/);
    expect(CMOD).toMatch(/email: cust\?\.email, phone: cust\?\.phone,/);
  });
});


/* ── (d) + (e) VisitRecapModal — behavioural SMS-pill availability ─ */
function _render(customer) {
  render(
    <VisitRecapModal
      serviceReportId="sr-test"
      customer={customer}
      onClose={vi.fn()}
    />,
  );
}

describe("APR-III · (d)/(e) VisitRecapModal SMS pill fallback-to-primary-only", () => {
  it("(d) customer with phone='' and legacy alert_phone populated → SMS pill is DISABLED", () => {
    _render({
      name: "APR tester",
      phone: "",
      // Legacy field still on the dict (grandfathered Mongo doc) —
      // the modal must IGNORE it post-APR.
      alert_phone: "+16025559999",
      email: "",
    });
    const smsPill = screen.getByTestId("visit-recap-channel-sms");
    expect(smsPill.disabled).toBe(true);
  });

  it("(e) customer with phone populated → SMS pill is ENABLED", () => {
    _render({
      name: "APR tester",
      phone: "+16025550102",
      email: "",
    });
    const smsPill = screen.getByTestId("visit-recap-channel-sms");
    expect(smsPill.disabled).toBe(false);
  });

  it("source-level lock — hasPhone no longer references customer.alert_phone", () => {
    // Belt-and-braces: the inline fallback is simplified to a single
    // read against ``customer?.phone`` only.
    expect(VMOD).toMatch(/const hasPhone = !!customer\?\.phone;/);
    expect(VMOD).not.toMatch(/customer\?\.alert_phone/);
    expect(VMOD).not.toMatch(/alert_phone/);
  });
});
