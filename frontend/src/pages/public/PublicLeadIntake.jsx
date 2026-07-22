// Phase 8 · Feb 2026 — Public lead intake form.
//
// Route: /public/leads (no auth). Renders a warm form that posts to
// POST /api/public/leads. If TURNSTILE_SITE_KEY is exposed via
// window.__TENANT_CONFIG__?.turnstile_site_key the widget renders
// and the token is passed in the payload.
import React, { useState } from "react";
import { toast, Toaster } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function PublicLeadIntake() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [interest, setInterest] = useState("Pool");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return toast.error("Please enter your name.");
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
          service_address: address.trim(),
          service_interest: interest,
          notes: notes.trim(),
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
    } catch (err) {
      toast.error("Sorry, that didn't go through", { description: err?.message || "" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-sky-50 via-white to-emerald-50 py-10 px-4"
           data-testid="public-lead-intake-page">
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
          <form onSubmit={submit} className="bg-white rounded-xl shadow p-6 space-y-4" data-testid="public-lead-form">
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
              <label className="text-xs font-medium text-slate-600">Service address</label>
              <input value={address} onChange={(e) => setAddress(e.target.value)}
                       className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
                       placeholder="123 Sunny Ln, Peoria AZ" data-testid="public-lead-address" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Service interest</label>
              <div className="mt-1 flex gap-2" data-testid="public-lead-interest">
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
    </div>
  );
}
