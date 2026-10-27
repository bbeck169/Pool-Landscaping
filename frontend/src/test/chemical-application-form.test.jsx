/**
 * Feb-2026 · C4 · ``ChemicalApplicationForm`` create/edit page.
 *
 * Covers (see C4 dispatch enumeration):
 *   1. All 7 sections render in create mode.
 *   2. Title flips 'New' <-> 'Edit' by ``:id`` param.
 *   3. Client-side required-field validation blocks submit.
 *   4. Customer select auto-fills ``property_address``.
 *   5. "Get Live Weather" disabled when no customer selected.
 *   6. Weather fetch 200 → fills 4 fields + weather_source badge +
 *      success toast.
 *   7. Weather fetch 404 → 'Address not recognized' error toast.
 *   8. Weather fetch 500 WEATHER_CONFIG_ERROR → 'not configured'.
 *   9. Chemical details: negative area → validation error.
 *  10. REI live helper renders when date + start + hours all present.
 *  11. License-number field is read-only from ``useAuth().user``.
 *  12. License missing → yellow warning shown, submit still enabled.
 *  13. Photo uploader onUploaded → attachment appears in list.
 *  14. Submit sends correct payload shape to
 *      ``POST /chemical-applications``.
 *  15. Submit success → navigate to ``/admin/chemical-applications/:id``.
 *  16. Submit 422 → inline field errors rendered.
 *  17. Edit mode fetches existing record and populates fields.
 *  18. Non-admin on edit route → locked banner.
 *  19. (in the C3 list test file) List "+ New Application" button
 *      navigates to /admin/chemical-applications/new.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


const {
  apiGetSpy, apiPostSpy, apiPatchSpy,
  toastSuccessSpy, toastErrorSpy,
  navigateSpy,
} = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  apiPostSpy: vi.fn(),
  apiPatchSpy: vi.fn(),
  toastSuccessSpy: vi.fn(),
  toastErrorSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));


// Configurable per-test ``useParams`` return + ``useAuth`` return.
// ``searchState`` mirrors ``useSearchParams()`` for the C5 hydration
// branch — each test can set specific query params before render.
const { authState, paramsState, searchState } = vi.hoisted(() => ({
  authState: { user: { id: "u1", name: "Alex Admin",
                        applicator_license_number: "TX-12345",
                        role: "admin" },
                role: "admin" },
  paramsState: {},
  searchState: new URLSearchParams(),
}));


vi.mock("@/api", () => ({
  api: {
    get:   (...a) => apiGetSpy(...a),
    post:  (...a) => apiPostSpy(...a),
    patch: (...a) => apiPatchSpy(...a),
  },
}));


vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccessSpy(...a),
    error:   (...a) => toastErrorSpy(...a),
  },
}));


vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFFFFF", surfaceSecondary: "#F4F4F5", surfaceTertiary: "#E4E4E7",
    border: "#E4E4E7", muted: "#71717A",
    brand: "#0284C7", brandPrimary: "#0284C7", onBrandPrimary: "#FFFFFF",
    onSurface: "#09090B", onSurfaceSecondary: "#52525B",
    success: "#16A34A", error: "#DC2626",
    inputBorder: "#3B82F6", searchIcon: "#0284C7",
    nav: { bg: "#1B1F5C", fg: "#FFFFFF", border: "rgba(255,255,255,0.10)" },
    gradient: { css: "linear-gradient(90deg,#1B1F5C,#0284C7)" },
  },
}));


vi.mock("@/auth", () => ({
  useAuth: () => authState,
}));


vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateSpy,
  useParams: () => paramsState,
  useSearchParams: () => [searchState, () => {}],
  Link: ({ children, to, ...rest }) => <a href={to} {...rest}>{children}</a>,
}));


// CustomerCombobox is a shadcn Popover; swap for a native ``<select>``
// so ``fireEvent.change`` can drive it.
vi.mock("@/components/customers/CustomerCombobox", () => {
  const Stub = ({ value, onChange, customers, testid, placeholder, disabled }) => (
    <select value={value || ""}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            data-testid={testid || "customer-combobox"}>
      <option value="">{placeholder || "All customers"}</option>
      {(customers || []).map((c) => (
        <option key={c.id} value={c.id}>{c.name || c.id}</option>
      ))}
    </select>
  );
  return { __esModule: true, default: Stub, CustomerCombobox: Stub };
});


// FileUpload spawns an XHR uploader — swap for a probe that fires
// ``onUploaded`` with a canned payload when its test button is clicked.
vi.mock("@/components/files/FileUpload", () => {
  const Stub = ({ onUploaded, disabled }) => (
    <div data-testid="file-upload-stub">
      <button type="button"
              disabled={disabled}
              onClick={() => onUploaded && onUploaded({
                id: "att-1", url: "https://cdn.test/attachments/att-1.jpg",
                filename: "spray-site.jpg", content_type: "image/jpeg",
                size_bytes: 12345,
              })}
              data-testid="file-upload-stub-add">
        Simulate upload
      </button>
    </div>
  );
  return { __esModule: true, default: Stub, FileUpload: Stub };
});


import ChemicalApplicationForm from "../pages/chemical/ChemicalApplicationForm";


// ─── Helper · commit a <DecimalInput>-backed value ────────────────
// ZZ-A · Feb-2026 — Four numeric fields (``temp-f``, ``wind-mph``,
// ``amount-sprayed-gal``, ``concentrate-oz``) migrated to the
// ``<DecimalInput>`` primitive during the Feb-2026 CHECKLIST-
// DECIMAL-INPUT-FIX parity sweep. That primitive is a ``type="text"``
// input that commits to the parent's ``onChange`` ONLY on blur /
// Enter / explicit ``commit()`` — ``fireEvent.change(...)`` alone
// updates the DOM raw buffer but never fires the parent commit, so
// ``form.<field>`` stays at ``""`` and the POST payload coerces to
// ``0`` via ``Number("")``. See ``DecimalInput.jsx:93-115`` for the
// commit contract.
//
// Previously-passing cases (L357/L359/L386) that only READ
// ``.value`` from these testids still work because the primitive's
// ``useEffect`` syncs the external value → raw buffer when
// unfocused, which is exactly what a parent-driven population does.
function _commitDecimal(testid, value) {
  const el = screen.getByTestId(testid);
  fireEvent.change(el, { target: { value } });
  fireEvent.blur(el);
}


// ═══════════════════════════════════════════════════════════════════
// Fixtures
// ═══════════════════════════════════════════════════════════════════
const CUSTOMERS = [
  { id: "cust-1", name: "Alpha HOA", address_line1: "123 Main St",
    city: "Austin", state: "TX", postal_code: "78701" },
  { id: "cust-2", name: "Beta Estates", address: "5 Beta Lane, Round Rock TX 78681" },
];


const WEATHER_SNAPSHOT = {
  temp_f: 72.5, humidity_pct: 58, wind_mph: 6.4, wind_direction: "SW",
  conditions: "Clear", fetched_at: "2026-02-20T18:04:00.000Z",
  source: "openweather", lat: 30.2672, lon: -97.7431,
  resolved_address: "Austin, Texas, US",
};


function _installApiMocks({
  weather = { ok: true, payload: WEATHER_SNAPSHOT },
  postResp = { ok: true, payload: { id: "new-1" } },
  patchResp = null,
  existingRecord = null,
} = {}) {
  apiGetSpy.mockReset(); apiPostSpy.mockReset(); apiPatchSpy.mockReset();

  apiGetSpy.mockImplementation((path) => {
    if (path === "/customers") return Promise.resolve(CUSTOMERS);
    if (path === "/technicians") return Promise.resolve([]);
    if (typeof path === "string" && path.startsWith("/weather/openweather/current")) {
      if (weather.ok) return Promise.resolve(weather.payload);
      const err = new Error(weather.error?.message || "err");
      err.status = weather.error?.status;
      err.data = { detail: weather.error?.detail };
      return Promise.reject(err);
    }
    if (typeof path === "string" && path.startsWith("/chemical-applications/")) {
      if (existingRecord) return Promise.resolve(existingRecord);
      return Promise.resolve(null);
    }
    return Promise.resolve({});
  });

  apiPostSpy.mockImplementation(() => {
    if (postResp.ok) return Promise.resolve(postResp.payload);
    const err = new Error(postResp.error?.message || "err");
    err.status = postResp.error?.status;
    err.data = { detail: postResp.error?.detail };
    return Promise.reject(err);
  });

  apiPatchSpy.mockImplementation(() => {
    if (patchResp && patchResp.ok) return Promise.resolve(patchResp.payload);
    return Promise.resolve({});
  });
}


beforeEach(() => {
  // Reset ambient mocks + auth + params + search.
  paramsState.id = undefined;
  // Recreate the URLSearchParams instance so leftover keys from the
  // previous test don't leak into the next.
  searchState.forEach((_, k) => searchState.delete(k));
  authState.user = { id: "u1", name: "Alex Admin",
                       applicator_license_number: "TX-12345",
                       role: "admin" };
  authState.role = "admin";
  _installApiMocks();
  toastSuccessSpy.mockReset();
  toastErrorSpy.mockReset();
  navigateSpy.mockReset();
});

afterEach(() => {
  cleanup();
});


// ═══════════════════════════════════════════════════════════════════
// 1 + 2. Sections + title flip
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — chrome", () => {
  it("renders all 7 sections in create mode with 'New Application' title", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-title").textContent)
        .toContain("New Application");
    });
    // Field markers (one per section is sufficient — the section
    // headers are decorative, the fields are the load-bearing DOM).
    expect(screen.getByTestId("chem-app-form-application-date")).toBeTruthy();
    expect(screen.getByTestId("chem-app-form-customer")).toBeTruthy();
    expect(screen.getByTestId("chem-app-form-temp-f")).toBeTruthy();
    expect(screen.getByTestId("chem-app-form-chemical-name")).toBeTruthy();
    expect(screen.getByTestId("chem-app-form-rei-hours")).toBeTruthy();
    expect(screen.getByTestId("chem-app-form-photos-section")).toBeTruthy();
    expect(screen.getByTestId("chem-app-form-notes")).toBeTruthy();
    expect(screen.getByTestId("chem-app-form-submit")).toBeTruthy();
  });

  it("shows 'Edit Application' title when :id param present", async () => {
    paramsState.id = "app-99";
    _installApiMocks({ existingRecord: {
      id: "app-99", application_date: "2026-02-19",
      start_time: "09:00:00", stop_time: "09:45:00",
      customer_id: "cust-1", property_address: "123 Main St",
      chemical_name: "Roundup", area_treated_sqft: 100,
      amount_sprayed_gal: 1, concentrate_oz: 8,
      target_pest: "Poa annua", rei_hours: 24, attachments: [], notes: "",
    }});
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-title").textContent)
        .toContain("Edit Application");
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 3. Required-field validation blocks submit
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — validation", () => {
  it("blocks submit + shows customer-required error when customer is empty", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-submit")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chem-app-form-submit"));
    await waitFor(() => {
      expect(toastErrorSpy).toHaveBeenCalled();
    });
    expect(apiPostSpy).not.toHaveBeenCalled();
  });

  it("rejects negative area with a field-level error", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-customer")).toBeTruthy();
    });
    // Populate every other required field so ONLY the area check fires.
    fireEvent.change(screen.getByTestId("chem-app-form-customer"), { target: { value: "cust-1" } });
    fireEvent.change(screen.getByTestId("chem-app-form-chemical-name"), { target: { value: "Roundup" } });
    fireEvent.change(screen.getByTestId("chem-app-form-area-treated-sqft"), { target: { value: "-5" } });
    _commitDecimal("chem-app-form-amount-sprayed-gal", "1");
    _commitDecimal("chem-app-form-concentrate-oz", "8");
    fireEvent.change(screen.getByTestId("chem-app-form-target-pest"), { target: { value: "Poa annua" } });
    fireEvent.change(screen.getByTestId("chem-app-form-rei-hours"), { target: { value: "24" } });
    // ``fireEvent.submit(form)`` — the submit button lives inside a
    // ``position: fixed`` container and its click-through chain has
    // occasional races with rapid pre-click state updates under
    // jsdom. Firing submit on the form directly is deterministic.
    fireEvent.submit(screen.getByTestId("chem-app-form"));
    await waitFor(() => { expect(toastErrorSpy).toHaveBeenCalled(); });
    expect(apiPostSpy).not.toHaveBeenCalled();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 4. Customer select auto-fills property_address
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — customer + weather wiring", () => {
  it("auto-fills property_address from customer on select", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-customer")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("chem-app-form-customer"),
                       { target: { value: "cust-1" } });
    await waitFor(() => {
      const el = screen.getByTestId("chem-app-form-property-address");
      // "123 Main St, Austin, TX 78701" composed via _composeCustomerAddress.
      expect(el.value).toContain("123 Main St");
      expect(el.value).toContain("Austin");
      expect(el.value).toContain("TX 78701");
    });
  });

  // ─── 5. Weather button disabled when no customer selected ────
  it("disables 'Get Live Weather' until a customer is selected", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-fetch-weather")).toBeTruthy();
    });
    expect(screen.getByTestId("chem-app-form-fetch-weather").disabled).toBe(true);
    fireEvent.change(screen.getByTestId("chem-app-form-customer"),
                       { target: { value: "cust-1" } });
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-fetch-weather").disabled).toBe(false);
    });
  });

  // ─── 6. Weather fetch 200 auto-fills 4 fields + badge + toast ─
  it("weather fetch 200 → fills 4 weather fields + weather_source badge + success toast", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-fetch-weather")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("chem-app-form-customer"),
                       { target: { value: "cust-1" } });
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-fetch-weather").disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId("chem-app-form-fetch-weather"));
    await waitFor(() => {
      expect(toastSuccessSpy).toHaveBeenCalled();
    });
    expect(String(screen.getByTestId("chem-app-form-temp-f").value)).toBe("72.5");
    expect(String(screen.getByTestId("chem-app-form-humidity-pct").value)).toBe("58");
    expect(String(screen.getByTestId("chem-app-form-wind-mph").value)).toBe("6.4");
    expect(screen.getByTestId("chem-app-form-wind-direction").value).toBe("SW");
    expect(screen.getByTestId("chem-app-form-weather-source-badge").textContent)
      .toContain("OpenWeather");
  });

  // ─── 7. Weather fetch 404 ─────────────────────────────────────
  it("weather fetch 404 → 'Address not recognized' toast, weather fields untouched", async () => {
    _installApiMocks({
      weather: { ok: false, error: { status: 404, message: "not found" } },
    });
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-fetch-weather")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("chem-app-form-customer"),
                       { target: { value: "cust-1" } });
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-fetch-weather").disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId("chem-app-form-fetch-weather"));
    await waitFor(() => {
      expect(toastErrorSpy).toHaveBeenCalled();
    });
    const msg = String(toastErrorSpy.mock.calls[0][0]).toLowerCase();
    expect(msg).toContain("address");
    expect(msg).toContain("not recognized");
    expect(screen.getByTestId("chem-app-form-temp-f").value).toBe("");
  });

  // ─── 8. Weather fetch 500 WEATHER_CONFIG_ERROR ────────────────
  it("weather fetch 500 WEATHER_CONFIG_ERROR → 'not configured' toast", async () => {
    _installApiMocks({
      weather: {
        ok: false,
        error: {
          status: 500, message: "cfg",
          detail: { code: "WEATHER_CONFIG_ERROR", message: "missing key" },
        },
      },
    });
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-customer")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("chem-app-form-customer"),
                       { target: { value: "cust-1" } });
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-fetch-weather").disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId("chem-app-form-fetch-weather"));
    await waitFor(() => { expect(toastErrorSpy).toHaveBeenCalled(); });
    const msg = String(toastErrorSpy.mock.calls[0][0]).toLowerCase();
    expect(msg).toContain("not configured");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 10. REI live helper
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — REI helper", () => {
  it("renders the reentry-unlocks-at helper when date + start + hours are all present", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-rei-hours")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("chem-app-form-application-date"),
                       { target: { value: "2026-02-20" } });
    fireEvent.change(screen.getByTestId("chem-app-form-start-time"),
                       { target: { value: "09:00" } });
    fireEvent.change(screen.getByTestId("chem-app-form-rei-hours"),
                       { target: { value: "24" } });
    await waitFor(() => {
      const preview = screen.getByTestId("chem-app-form-rei-unlock-preview");
      expect(preview.textContent).toContain("Reentry unlocks at");
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 11 + 12. License number field
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — license number", () => {
  it("renders license number from useAuth().user.applicator_license_number as read-only", async () => {
    authState.user = { id: "u1", name: "Alex Admin",
                         applicator_license_number: "TX-99999",
                         role: "admin" };
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-license-number").textContent)
        .toContain("TX-99999");
    });
    // No missing-license warning when a value is present.
    expect(screen.queryByTestId("chem-app-form-license-missing-warning")).toBeNull();
  });

  it("shows missing-license warning when applicator_license_number is null; submit stays enabled", async () => {
    authState.user = { id: "u1", name: "Alex Admin",
                         applicator_license_number: null,
                         role: "admin" };
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-license-missing-warning")).toBeTruthy();
    });
    expect(screen.getByTestId("chem-app-form-submit").disabled).toBe(false);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 13. Photo uploader appends URLs
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — photo uploader", () => {
  it("uploader onUploaded → attachment appears in list", async () => {
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("file-upload-stub-add")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("file-upload-stub-add"));
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-attachment-0")).toBeTruthy();
    });
    expect(screen.getByTestId("chem-app-form-attachment-0").textContent)
      .toContain("spray-site.jpg");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 14 + 15. Submit — payload shape + navigate on success
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — submit", () => {
  it("POST /chemical-applications with correct payload + navigate on success", async () => {
    _installApiMocks({ postResp: { ok: true, payload: { id: "new-42" } } });
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-customer")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("chem-app-form-customer"),
                       { target: { value: "cust-1" } });
    fireEvent.change(screen.getByTestId("chem-app-form-application-date"),
                       { target: { value: "2026-02-20" } });
    fireEvent.change(screen.getByTestId("chem-app-form-start-time"),
                       { target: { value: "09:00" } });
    fireEvent.change(screen.getByTestId("chem-app-form-stop-time"),
                       { target: { value: "09:45" } });
    fireEvent.change(screen.getByTestId("chem-app-form-chemical-name"),
                       { target: { value: "Roundup PowerMAX" } });
    fireEvent.change(screen.getByTestId("chem-app-form-area-treated-sqft"),
                       { target: { value: "5000" } });
    _commitDecimal("chem-app-form-amount-sprayed-gal", "2.5");
    _commitDecimal("chem-app-form-concentrate-oz", "12");
    fireEvent.change(screen.getByTestId("chem-app-form-target-pest"),
                       { target: { value: "Poa annua" } });
    fireEvent.change(screen.getByTestId("chem-app-form-rei-hours"),
                       { target: { value: "24" } });
    fireEvent.submit(screen.getByTestId("chem-app-form"));

    await waitFor(() => { expect(apiPostSpy).toHaveBeenCalledTimes(1); });
    const [path, body] = apiPostSpy.mock.calls[0];
    expect(path).toBe("/chemical-applications");
    expect(body.customer_id).toBe("cust-1");
    expect(body.chemical_name).toBe("Roundup PowerMAX");
    expect(body.area_treated_sqft).toBe(5000);
    expect(body.amount_sprayed_gal).toBe(2.5);
    expect(body.concentrate_oz).toBe(12);
    expect(body.rei_hours).toBe(24);
    expect(body.start_time).toBe("09:00:00");
    expect(body.stop_time).toBe("09:45:00");

    await waitFor(() => { expect(toastSuccessSpy).toHaveBeenCalled(); });
    await waitFor(() => {
      expect(navigateSpy).toHaveBeenCalledWith("/admin/chemical-applications/new-42");
    });
  });

  // ─── 16. Submit 422 renders inline field errors ─────────────
  it("422 response → inline field errors from backend detail", async () => {
    _installApiMocks({
      postResp: {
        ok: false,
        error: {
          status: 422, message: "bad",
          detail: [
            { loc: ["body", "concentrate_oz"], msg: "Field required" },
          ],
        },
      },
    });
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-customer")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("chem-app-form-customer"),
                       { target: { value: "cust-1" } });
    fireEvent.change(screen.getByTestId("chem-app-form-chemical-name"),
                       { target: { value: "Roundup" } });
    fireEvent.change(screen.getByTestId("chem-app-form-area-treated-sqft"),
                       { target: { value: "5000" } });
    _commitDecimal("chem-app-form-amount-sprayed-gal", "2");
    _commitDecimal("chem-app-form-concentrate-oz", "8");
    fireEvent.change(screen.getByTestId("chem-app-form-target-pest"),
                       { target: { value: "Poa annua" } });
    fireEvent.change(screen.getByTestId("chem-app-form-rei-hours"),
                       { target: { value: "24" } });
    fireEvent.submit(screen.getByTestId("chem-app-form"));
    await waitFor(() => { expect(apiPostSpy).toHaveBeenCalled(); });
    // Server-driven error map — the concentrate_oz row's ErrorText
    // renders the backend msg.
    await waitFor(() => {
      // ErrorText renders as plain text inside the field — sanity-check
      // by looking for the substring anywhere in the document.
      expect(screen.getByText(/Field required/i)).toBeTruthy();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 17. Edit mode fetches + populates
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — edit mode", () => {
  it("fetches the existing record via /chemical-applications/:id and populates fields", async () => {
    paramsState.id = "app-77";
    _installApiMocks({ existingRecord: {
      id: "app-77", application_date: "2026-02-15",
      start_time: "14:30:00", stop_time: "15:00:00",
      customer_id: "cust-2", property_address: "5 Beta Lane",
      chemical_name: "Turflon Ester", area_treated_sqft: 3200,
      amount_sprayed_gal: 1.8, concentrate_oz: 6,
      target_pest: "Bermuda encroachment", rei_hours: 24,
      temp_f: 68, humidity_pct: 61, wind_mph: 4, wind_direction: "N",
      weather_source: "openweather",
      weather_fetched_at: "2026-02-15T14:20:00Z",
      attachments: [], notes: "Edge treatment along fence line.",
    }});
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-chemical-name").value)
        .toBe("Turflon Ester");
    });
    expect(screen.getByTestId("chem-app-form-target-pest").value)
      .toBe("Bermuda encroachment");
    expect(String(screen.getByTestId("chem-app-form-area-treated-sqft").value))
      .toBe("3200");
    expect(screen.getByTestId("chem-app-form-notes").value)
      .toContain("Edge treatment");
    // Weather source badge stays 'openweather'.
    expect(screen.getByTestId("chem-app-form-weather-source-badge")).toBeTruthy();
  });

  // ─── 18. Non-admin on edit route → locked banner ─────────────
  it("non-admin (manager) sees the role-lock banner on edit route and submit is disabled", async () => {
    paramsState.id = "app-88";
    authState.user = { id: "u2", name: "Marge Manager",
                         applicator_license_number: "TX-55555",
                         role: "manager" };
    authState.role = "manager";
    _installApiMocks({ existingRecord: {
      id: "app-88", application_date: "2026-02-15",
      start_time: "10:00:00", stop_time: "10:30:00",
      customer_id: "cust-1", property_address: "123 Main St",
      chemical_name: "Prodiamine", area_treated_sqft: 100,
      amount_sprayed_gal: 1, concentrate_oz: 8,
      target_pest: "Poa annua", rei_hours: 12,
      attachments: [], notes: "",
    }});
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-role-lock")).toBeTruthy();
    });
    expect(screen.getByTestId("chem-app-form-submit").disabled).toBe(true);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 19. C5 · ?customer_id=<id> deep-link hydration (create mode)
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationForm — C5 deep-link hydration", () => {
  it("in create mode with ?customer_id=<id>, pre-selects the customer + auto-fills property_address", async () => {
    // Land on /admin/chemical-applications/new?customer_id=cust-1.
    searchState.set("customer_id", "cust-1");
    render(<ChemicalApplicationForm />);
    // Wait for the customer list to load and the hydration effect
    // to fire (2nd render pass after customers arrive).
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-form-customer").value).toBe("cust-1");
    });
    // Property address hydrated from cust-1's structured address fields.
    await waitFor(() => {
      const el = screen.getByTestId("chem-app-form-property-address");
      expect(el.value).toContain("123 Main St");
      expect(el.value).toContain("Austin");
    });
    // The Get Live Weather button is unlocked (customer is selected).
    expect(screen.getByTestId("chem-app-form-fetch-weather").disabled).toBe(false);
  });

  it("in edit mode, ?customer_id query param is IGNORED (edit record wins)", async () => {
    paramsState.id = "app-77";
    searchState.set("customer_id", "cust-1");
    _installApiMocks({ existingRecord: {
      id: "app-77", application_date: "2026-02-15",
      start_time: "10:00:00", stop_time: "10:30:00",
      customer_id: "cust-2", property_address: "5 Beta Lane",
      chemical_name: "Turflon", area_treated_sqft: 3200,
      amount_sprayed_gal: 1.8, concentrate_oz: 6,
      target_pest: "Bermuda", rei_hours: 24,
      attachments: [], notes: "",
    }});
    render(<ChemicalApplicationForm />);
    await waitFor(() => {
      // Customer stays as the edit record's cust-2, NOT the query's cust-1.
      expect(screen.getByTestId("chem-app-form-customer").value).toBe("cust-2");
    });
  });
});
