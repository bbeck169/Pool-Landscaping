// Phase 8 · Feb 2026 — Public lead intake form.
//
// Route: /public/leads (no auth). Renders a warm form that posts to
// POST /api/public/leads. If TURNSTILE_SITE_KEY is exposed via
// window.__TENANT_CONFIG__?.turnstile_site_key the widget renders
// and the token is passed in the payload.
import React, { useState, useEffect } from "react";
import { toast, Toaster } from "sonner";
import ThemedFormShell from "../../components/formBuilder/ThemedFormShell";
import AddressAutocomplete from "../../components/common/AddressAutocomplete";

const API = process.env.REACT_APP_BACKEND_URL;

export default function PublicLeadIntake() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  // Feb-2026 · P0 · Lead form address autofill — coords captured
  // via Google Places autocomplete are attached to the POST payload
  // so the backend skips its on-save geocode call.
  const [latitude, setLatitude] = useState(null);
  const [longitude, setLongitude] = useState(null);
  const [interest, setInterest] = useState("Pool");
  const [notes, setNotes] = useState("");
  // Feb-2026 · Street-address capture — inline error string
  // surfaced via ``lead-form-address-error`` so browser tests can
  // assert the validation failure without waiting on toast copy.
  const [addressErr, setAddressErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState(false);
  // K34 · Feb-2026 — pick up an optional ``theme`` object exposed
  // by ``window.__TENANT_CONFIG__``.  Falls back to null so the
  // default (pre-K34) app look is preserved for tenants that
  // haven't picked a theme yet.
  const [theme, setTheme] = useState(null);
  // CUS-Marketing-Form-Builder · Feb-2026 — Phase 4 widget parity.
  // Optional hero band configuration mirrors ``schema.hero`` on the
  // dynamic widget path. Tenants that want a hero banner on the
  // hardcoded lead-intake page publish it via
  // ``window.__TENANT_CONFIG__.form_hero`` following the same shape
  // Phase 3's HeroEditor emits (heading_html, subheading_html,
  // background{kind,color|url|gradient}, badge). Null → renders
  // exactly as pre-Phase-4.
  //
  // Note: ``column_span`` is intentionally NOT applied on this page
  // because ``PublicLeadIntake`` renders a hardcoded set of fields
  // (name / email / phone / address / interest / notes) rather than
  // iterating over a dynamic ``schema.fields`` array. Column-span
  // is a widget-only feature — dynamic layout only makes sense on
  // the dynamic renderer.
  const [hero, setHero] = useState(null);
  useEffect(() => {
    const t = (typeof window !== "undefined"
                && window.__TENANT_CONFIG__?.form_theme) || null;
    if (t) setTheme(t);
    const h = (typeof window !== "undefined"
                && window.__TENANT_CONFIG__?.form_hero) || null;
    if (h) setHero(h);
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    // Feb-2026 · Street-address capture — mirror the server-side
    // required-field enum. Client blocks the submit + surfaces the
    // ``lead-form-address-error`` testid so downstream marketing
    // dashboards + lead extraction never see empty addresses.
    const _addrRaw = address.trim();
    if (!name.trim()) return toast.error("Please enter your name.");
    if (_addrRaw.length < 3) {
      setAddressErr("Street address is required.");
      return toast.error("Please enter your street address.");
    }
    setAddressErr("");
    if (!email.trim() && !phone.trim())
      return toast.error("Please provide an email or a phone number.");
    setBusy(true);
    try {
      const res = await fetch(`${API}/api/public/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          phone: phone.trim(),
          // Feb-2026 · lead extraction — send BOTH the modern
          // ``address`` key + the legacy ``service_address`` key
          // for backwards-compat with older extractors that only
          // look at ``service_address``. Backend
          // ``lead_extraction._ADDRESS_ALIASES`` already resolves
          // either to the same lead-record field.
          address: _addrRaw,
          service_address: _addrRaw,
          service_interest: interest,
          notes: notes.trim(),
          // Feb-2026 · P0 — attach autocomplete-resolved coordinates
          // when present so the backend skips its on-save geocode.
          latitude,
          longitude,
        }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }
      setOk(true);
      toast.success("Thanks — we'll be in touch within one business day.");
      // Clear the form.
      setName(""); setEmail(""); setPhone("");
      setAddress(""); setNotes(""); setInterest("Pool");
      setLatitude(null); setLongitude(null);
    } catch (err) {
      toast.error("Sorry, that didn't go through", { description: err?.message || "" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ThemedFormShell theme={theme}
                      hero={hero}
                      testid="public-lead-intake-page"
                      className={theme
                        ? "min-h-screen py-10 px-4"
                        : "min-h-screen bg-gradient-to-br from-sky-50 via-white to-emerald-50 py-10 px-4"}>
      <Toaster position="top-center" richColors />
      <div className="max-w-lg mx-auto">
        <div className="text-center mb-6">
          <div className="text-xs uppercase tracking-widest text-sky-600 font-semibold">
            Pool & Landscaping of Vistancia
          </div>
          <h1 className="text-3xl font-bold text-slate-900 mt-1">Request a quote</h1>
          <p className="text-slate-600 text-sm mt-2">
            Tell us a little about your property and we'll be in touch within one business day.
          </p>
        </div>

        {ok ? (
          <div className="bg-white rounded-xl shadow p-6 text-center" data-testid="public-lead-success">
            <div className="text-4xl mb-2">🌵</div>
            <h2 className="text-xl font-semibold text-slate-900 mb-1">Thanks — you're on the list.</h2>
            <p className="text-slate-600 text-sm">
              One of our team will reach out within one business day. In the meantime,
              feel free to call us anytime at <b>+1 (602) 887-4400</b>.
            </p>
            <button className="mt-4 px-4 py-2 rounded bg-sky-600 hover:bg-sky-700 text-white text-sm"
                      onClick={() => setOk(false)}
                      data-testid="public-lead-another">
              Submit another
            </button>
          </div>
        ) : (
          <form onSubmit={submit}
                    noValidate
                    className="bg-white rounded-xl shadow p-6 space-y-4"
                    data-testid="public-lead-form">
            <div>
              <label className="text-xs font-medium text-slate-600">Your name *</label>
              <input value={name} onChange={(e) => setName(e.target.value)}
                       className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
                       placeholder="Jane Smith" data-testid="public-lead-name" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-slate-600">Email</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                         className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
                         placeholder="jane@example.com" data-testid="public-lead-email" />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-600">Phone</label>
                <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)}
                         className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
                         placeholder="+1 (602) 555-0100" data-testid="public-lead-phone" />
              </div>
            </div>
            <div className="text-xs text-slate-500 -mt-2">
              Email OR phone required — we'll use whichever you prefer.
            </div>
            <div>
              <label htmlFor="address"
                       className="text-xs font-medium text-slate-600">
                Street Address <span aria-hidden="true" style={{ color: "#B91C1C" }}>*</span>
              </label>
              <div className="mt-1" data-testid="lead-form-address-autocomplete-wrapper">
                <AddressAutocomplete
                  value={address}
                  onChange={(sel) => {
                    // Free-form typing arrives with lat/lng = null.
                    // A picked suggestion carries the resolved
                    // coordinates + parsed components.
                    setAddress(sel?.formatted || sel?.street || "");
                    setLatitude(sel?.latitude ?? null);
                    setLongitude(sel?.longitude ?? null);
                    if (addressErr) setAddressErr("");
                  }}
                  placeholder="123 Sunny Ln, Peoria AZ"
                  error={addressErr}
                  id="address"
                  name="address"
                  required
                  minLength={3}
                  ariaLabel="Street Address"
                  ariaDescribedBy={addressErr ? "address-error" : undefined}
                  testId="lead-form-address-input"
                />
              </div>
              {addressErr ? (
                <div
                  id="address-error"
                  className="mt-1 text-xs"
                  style={{ color: "#B91C1C" }}
                  role="alert"
                  data-testid="lead-form-address-error"
                >
                  {addressErr}
                </div>
              ) : null}
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Service interest</label>
              <div className="mt-1 flex gap-2"
                    data-testid="public-lead-interest">
                {/* Feb-2026 · Lead form — stable ``service_interest``
                    submission key + testid for downstream automation. */}
                <input type="hidden" name="service_interest"
                        value={interest}
                        data-testid="lead-form-service-interest" />
                {["Pool", "Landscape", "Both"].map((s) => (
                  <label key={s}
                            className={`flex-1 border rounded px-3 py-2 text-sm text-center cursor-pointer ${
                              interest === s
                                ? "border-sky-600 bg-sky-50 text-sky-800 font-medium"
                                : "border-slate-300 text-slate-700"
                            }`}>
                    <input type="radio" name="interest" value={s} className="sr-only"
                             checked={interest === s} onChange={() => setInterest(s)}
                             data-testid={`public-lead-interest-${s.toLowerCase()}`} />
                    {s}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Notes (optional)</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
                          rows={3}
                          className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
                          placeholder="Anything we should know about your property?"
                          data-testid="public-lead-notes" />
            </div>
            <button type="submit" disabled={busy}
                      className="w-full py-3 rounded bg-sky-600 hover:bg-sky-700 text-white text-sm font-medium disabled:opacity-60"
                      data-testid="public-lead-submit">
              {busy ? "Sending…" : "Request my quote"}
            </button>
            <p className="text-[11px] text-slate-500 text-center">
              By submitting you agree we may contact you by phone, email, or SMS.
              Reply STOP to opt out of texts at any time.
            </p>
          </form>
        )}
      </div>
    </ThemedFormShell>
  );
}
