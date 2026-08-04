/**
 * Phase 48 · Feb-2026 — Customer contact redesign source-inspection tests.
 *
 * Guards the visible-to-user behaviours the redesign spec required:
 *   • BusinessCard component NO longer mounted on the customer detail
 *     page (but the component itself stays in-tree — a separate
 *     backend test enforces that).
 *   • CustomerContactsPanel exposes the "Email / Mobile Phone /
 *     Home Phone" primary group + "Additional Mobile Phone up to 2"
 *     + "Additional Emails up to 3" groups with bold labels.
 *   • CustomerForm has 4-input service address + 4-input billing
 *     address + a home_phone field.
 *   • Composition helpers round-trip legacy address strings without
 *     data loss.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { _parseAddress, _composeAddress } from "@/pages/customers/CustomerForm";

const DETAIL = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");
const PANEL = resolve(__dirname, "../components/customers/CustomerContactsPanel.jsx");
const FORM = resolve(__dirname, "../pages/customers/CustomerForm.jsx");

const _detail = readFileSync(DETAIL, "utf8");
const _panel = readFileSync(PANEL, "utf8");
const _form = readFileSync(FORM, "utf8");

describe("Phase 48 · CustomerDetail.jsx no longer mounts <BusinessCard>", () => {
  it("does not render the BusinessCard slot on the overview tab", () => {
    // The Phase-48-removed slot must be gone.
    expect(_detail).not.toContain('data-testid="cd-business-card-slot"');
    expect(_detail).not.toMatch(/<BusinessCard\b[^/]*\/>/);
  });

  it("keeps the CustomerContactsPanel + MasterBillingCard mounts intact", () => {
    // Phase 48 is presentation-only — these other panels must still render.
    expect(_detail).toContain("<CustomerContactsPanel");
    expect(_detail).toContain("<MasterBillingCard");
  });
});

describe("Phase 48.1 · overview-tab reorder (name → contacts → address)", () => {
  // Locate source-order positions of the key blocks inside the overview
  // tab. A negative index means "not found" which is itself a failure.
  const _pos = (needle) => _detail.indexOf(needle);
  const _nameSecondary = _pos('data-testid="cd-customer-name-secondary"');
  const _contactsPanel = _pos("<CustomerContactsPanel");
  const _addressBlock = _pos('data-testid="cd-address-block"');
  const _masterBilling = _pos("<MasterBillingCard");

  it("mounts the secondary customer name marker inside the overview tab", () => {
    expect(_nameSecondary).toBeGreaterThan(0);
  });

  it("renders CustomerContactsPanel AFTER the secondary customer name", () => {
    expect(_contactsPanel).toBeGreaterThan(_nameSecondary);
  });

  it("renders the address block AFTER the CustomerContactsPanel", () => {
    // Phase 48.1 swaps the pre-existing order — address block was
    // rendered BEFORE ContactsPanel in Phase 48; now it sits after.
    expect(_addressBlock).toBeGreaterThan(_contactsPanel);
    // MasterBillingCard now sits below the address block (pushed down
    // by the reorder; no longer the first item in the overview tab).
    expect(_masterBilling).toBeGreaterThan(_addressBlock);
  });

  it("keeps the h1 customer name in the top header block", () => {
    // Phase 48.1 adds a secondary name marker inside the overview
    // tab — the primary h1 in the header stays put so breadcrumbs and
    // VIP toggle still anchor to the page title.
    expect(_detail).toMatch(
      /<h1[^>]*text-3xl[^>]*>\s*\{customer\.name\}\s*<\/h1>/,
    );
  });

  it("regression: <BusinessCard> stays unmounted post-reorder", () => {
    // Phase 48.1 is a visual reorder only — the Phase 48 guarantee
    // that BusinessCard is unmounted must not regress.
    expect(_detail).not.toContain('data-testid="cd-business-card-slot"');
    expect(_detail).not.toMatch(/<BusinessCard\b[^/]*\/>/);
  });
});

describe("Phase 48 · CustomerContactsPanel primary + additional groups", () => {
  // TextInput/Button use `testid=` prop (mapped to data-testid in the DOM);
  // raw JSX divs use `data-testid=`. Regex tolerates both.
  const _hasTestId = (id) =>
    new RegExp(`(?:data-)?testid=["']${id.replace(/[-]/g, "\\-")}["']`);

  it("renders the primary contact group with Email / Mobile / Home Phone", () => {
    expect(_panel).toMatch(_hasTestId("cd-primary-contact-group"));
    expect(_panel).toMatch(_hasTestId("cd-primary-email"));
    expect(_panel).toMatch(_hasTestId("cd-primary-mobile"));
    expect(_panel).toMatch(_hasTestId("cd-home-phone"));
    // Bold labels — the redesign spec called them out.
    expect(_panel).toMatch(/className="font-bold text-sm"/);
    // The literal labels users see (JSX renders them as text children,
    // possibly with whitespace between the tag and the text).
    expect(_panel).toMatch(/>\s*Email\s*</);
    expect(_panel).toMatch(/>\s*Mobile Phone\s*</);
    expect(_panel).toMatch(/>\s*Home Phone\s*</);
  });

  it("renders the Additional Mobile Phone group with an up-to-2 cap", () => {
    expect(_panel).toMatch(_hasTestId("cd-additional-mobiles-group"));
    expect(_panel).toContain("Additional Mobile Phone up to");
    expect(_panel).toContain("MAX_ADDITIONAL_MOBILES = MAX_MOBILES - 1");
    expect(_panel).toMatch(_hasTestId("cd-add-additional-mobile"));
    expect(_panel).toMatch(_hasTestId("cd-additional-mobiles-empty"));
  });

  it("renders the Additional Emails group with an up-to-3 cap", () => {
    expect(_panel).toMatch(_hasTestId("cd-additional-emails-group"));
    expect(_panel).toContain("Additional Emails up to");
    expect(_panel).toContain("MAX_ADDITIONAL_EMAILS = MAX_EMAILS - 1");
    expect(_panel).toMatch(_hasTestId("cd-add-additional-email"));
    expect(_panel).toMatch(_hasTestId("cd-additional-emails-empty"));
  });

  it("enforces the caps MAX_MOBILES=3 and MAX_EMAILS=4 in the panel constants", () => {
    expect(_panel).toContain("const MAX_MOBILES = 3");
    expect(_panel).toContain("const MAX_EMAILS = 4");
  });

  it("no longer renders the pre-Phase-48 label / primary-radio / consent controls", () => {
    expect(_panel).not.toContain("cd-mobile-label-");
    expect(_panel).not.toContain("cd-mobile-primary-");
    expect(_panel).not.toContain("cd-mobile-smsok-");
    expect(_panel).not.toContain("cd-email-primary-");
    expect(_panel).not.toContain("cd-email-mktok-");
  });
});

describe("Phase 48 · CustomerForm.jsx structured address + home_phone", () => {
  const _hasTestId = (id) =>
    new RegExp(`(?:data-)?testid=["']${id.replace(/[-]/g, "\\-")}["']`);

  it("renders 4-input service address group with the right testids", () => {
    for (const t of [
      "cf-service-address-group",
      "cf-service-street",
      "cf-service-city",
      "cf-service-state",
      "cf-service-zip",
    ]) {
      expect(_form).toMatch(_hasTestId(t));
    }
    expect(_form).toContain("Service Address");
  });

  it("renders 4-input billing address group with the right testids", () => {
    for (const t of [
      "cf-billing-address-group",
      "cf-billing-street",
      "cf-billing-city",
      "cf-billing-state",
      "cf-billing-zip",
    ]) {
      expect(_form).toMatch(_hasTestId(t));
    }
    expect(_form).toContain("Billing Address if Different");
  });

  it("renders a home_phone field in the primary-contact group", () => {
    expect(_form).toMatch(_hasTestId("cf-home-phone"));
    expect(_form).toMatch(/HOME PHONE/);
    // Regression guard against the label reverting to "PRIMARY PHONE".
    expect(_form).toContain("PRIMARY MOBILE PHONE");
  });

  it("composes structured fields into the legacy single-string on save", () => {
    expect(_form).toContain("_composeAddress({");
    expect(_form).toContain("street: form.service_street");
    expect(_form).toContain("street: form.billing_street");
    expect(_form).toContain('home_phone: (form.home_phone || "").trim()');
  });

  it("removes the single-string BILLING ADDRESS input (superseded by 4-input group)", () => {
    // Pre-Phase-48 the form had a single ``cf-billing`` TextInput.
    // Regex-scoped so ``cf-billing-street`` / etc. don't false-positive.
    expect(_form).not.toMatch(/(?:data-)?testid="cf-billing"/);
  });
});

describe("Phase 48 · _parseAddress / _composeAddress round-trip", () => {
  it("parses a canonical US address into 4 parts", () => {
    expect(_parseAddress("123 Main St, Phoenix, AZ 85001")).toEqual({
      street: "123 Main St",
      city: "Phoenix",
      state: "AZ",
      zip: "85001",
    });
  });

  it("supports the ZIP+4 form", () => {
    expect(_parseAddress("456 Oak Ave, Peoria, AZ 85345-1234")).toEqual({
      street: "456 Oak Ave",
      city: "Peoria",
      state: "AZ",
      zip: "85345-1234",
    });
  });

  it("keeps a multi-comma street intact if the last segment is a state+zip", () => {
    // "PO Box 42, Suite 3, Scottsdale, AZ 85251" — the city becomes
    // "Suite 3, Scottsdale" which is not ideal but zero data loss.
    const parsed = _parseAddress("PO Box 42, Suite 3, Scottsdale, AZ 85251");
    expect(parsed.street).toBe("PO Box 42");
    expect(parsed.state).toBe("AZ");
    expect(parsed.zip).toBe("85251");
    expect(parsed.city).toBe("Suite 3, Scottsdale");
  });

  it("puts un-parseable strings entirely in the street field (no data loss)", () => {
    // Legacy free-form entries that don't have a state+zip tail: dump
    // everything in street so the admin can clean it up in-place.
    expect(_parseAddress("Just something weird")).toEqual({
      street: "Just something weird", city: "", state: "", zip: "",
    });
    expect(_parseAddress("123 Main St, Phoenix")).toEqual({
      street: "123 Main St, Phoenix", city: "", state: "", zip: "",
    });
  });

  it("composes the 4 parts back into 'street, city, state zip'", () => {
    const round = _composeAddress({
      street: "123 Main St", city: "Phoenix", state: "AZ", zip: "85001",
    });
    expect(round).toBe("123 Main St, Phoenix, AZ 85001");
  });

  it("compose+parse is stable for canonical addresses", () => {
    const original = { street: "789 Elm", city: "Mesa", state: "AZ", zip: "85201" };
    expect(_parseAddress(_composeAddress(original))).toEqual(original);
  });

  it("compose skips empty parts cleanly", () => {
    expect(_composeAddress({ street: "123 Main St", city: "", state: "", zip: "" }))
      .toBe("123 Main St");
    expect(_composeAddress({ street: "", city: "", state: "", zip: "" })).toBe("");
  });
});
