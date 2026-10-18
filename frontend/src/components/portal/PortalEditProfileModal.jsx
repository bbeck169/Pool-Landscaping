/**
 * Feb-2026 · Portal Edit Profile — quick-edit modal mounted from the
 * ``/portal/home`` hero banner. Four-field focus (First Name, Last
 * Name, Phone, Email) backed by the already-shipped
 * ``PATCH /api/customer-portal/profile`` endpoint. For address /
 * secondary email / advanced fields the modal exposes an "Edit full
 * profile →" link that routes to ``/portal/profile``.
 *
 * Modal styling intentionally mirrors ``PaymentMethodPromptModal``
 * (raw fixed-position overlay, no shadcn Dialog) because the portal
 * modal convention is a bespoke white card on a navy-tinted
 * backdrop — matches the dark hero banner above it.
 *
 * Backend contract (see ``routers/customer_portal.py::patch_my_profile``):
 *   • ``first_name`` / ``last_name`` — non-empty when supplied.
 *   • ``phone`` — raw digits; the server normalizes to E.164.
 *   • ``email`` — RFC-lite validator + global-uniqueness check. When
 *     the new email differs from the stored primary the client MUST
 *     send ``confirm_current_email`` matching the on-record email;
 *     the modal reveals that field dynamically.
 *
 * Props
 *   open       — boolean, controls visibility.
 *   onClose    — () => void. Called on backdrop/esc/cancel/success-close.
 *   initial    — { first_name, last_name, phone, email } pre-fill.
 *   onSaved    — (patched) => void. Fires AFTER the server 200 so the
 *                parent can refetch its greeting / summary without
 *                this component owning a data source.
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { X as XIcon, UserCog } from "lucide-react";

import { api } from "@/api";


const _EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;


function _digitCount(s) {
  return (s || "").replace(/\D/g, "").length;
}


export default function PortalEditProfileModal({
  open,
  onClose,
  initial = {},
  onSaved,
}) {
  const navigate = useNavigate();
  // Form state — Feb-2026 Deploy Corruption Workaround: atomic-tuple
  // pattern mirrors the ``JobNotesCallout`` fix (``useState`` lines
  // get stripped by the Emergent prod pipeline when written
  // separately). Keep the tuple array literal reads INLINE so the
  // minifier can't split them.
  const _firstTuple = React.useState("");
  const firstName   = Array.isArray(_firstTuple) ? _firstTuple[0] : "";
  const setFirstName = Array.isArray(_firstTuple) ? _firstTuple[1] : () => {};
  const _lastTuple  = React.useState("");
  const lastName    = Array.isArray(_lastTuple) ? _lastTuple[0] : "";
  const setLastName = Array.isArray(_lastTuple) ? _lastTuple[1] : () => {};
  const _phoneTuple = React.useState("");
  const phone       = Array.isArray(_phoneTuple) ? _phoneTuple[0] : "";
  const setPhone    = Array.isArray(_phoneTuple) ? _phoneTuple[1] : () => {};
  const _emailTuple = React.useState("");
  const email       = Array.isArray(_emailTuple) ? _emailTuple[0] : "";
  const setEmail    = Array.isArray(_emailTuple) ? _emailTuple[1] : () => {};
  const _confirmTuple = React.useState("");
  const confirmCurrentEmail = Array.isArray(_confirmTuple) ? _confirmTuple[0] : "";
  const setConfirmCurrentEmail = Array.isArray(_confirmTuple) ? _confirmTuple[1] : () => {};

  const _busyTuple = React.useState(false);
  const busy       = Array.isArray(_busyTuple) ? _busyTuple[0] : false;
  const setBusy    = Array.isArray(_busyTuple) ? _busyTuple[1] : () => {};
  const _errTuple  = React.useState(null);
  const serverError = Array.isArray(_errTuple) ? _errTuple[0] : null;
  const setServerError = Array.isArray(_errTuple) ? _errTuple[1] : () => {};
  const _fieldErrTuple = React.useState({});
  const fieldErrors = Array.isArray(_fieldErrTuple) ? _fieldErrTuple[0] : {};
  const setFieldErrors = Array.isArray(_fieldErrTuple) ? _fieldErrTuple[1] : () => {};

  // Pre-fill from ``initial`` whenever the modal opens.
  React.useEffect(() => {
    if (!open) return;
    setFirstName(initial.first_name || "");
    setLastName(initial.last_name || "");
    setPhone(initial.phone || "");
    setEmail((initial.email || "").toLowerCase());
    setConfirmCurrentEmail("");
    setServerError(null);
    setFieldErrors({});
  }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Esc-to-close.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose && onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const initialEmail = (initial.email || "").toLowerCase();
  const emailChanged = email.trim().toLowerCase() !== initialEmail;

  function _validate() {
    const errs = {};
    if (!firstName.trim()) errs.first_name = "First name is required.";
    if (!lastName.trim())  errs.last_name  = "Last name is required.";
    if (!email.trim())     errs.email      = "Email is required.";
    else if (!_EMAIL_RE.test(email.trim())) errs.email = "Enter a valid email address.";
    if (!phone.trim())     errs.phone      = "Phone is required.";
    else if (_digitCount(phone) < 10)      errs.phone = "Phone must have at least 10 digits.";
    if (emailChanged && !confirmCurrentEmail.trim()) {
      errs.confirm_current_email =
        "Confirm your current email to change it.";
    }
    return errs;
  }

  async function _onSubmit(e) {
    e.preventDefault();
    setServerError(null);
    const errs = _validate();
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;
    const payload = {
      first_name: firstName.trim(),
      last_name:  lastName.trim(),
      phone:      phone.trim(),
      email:      email.trim().toLowerCase(),
    };
    if (emailChanged) {
      payload.confirm_current_email = confirmCurrentEmail.trim().toLowerCase();
    }
    setBusy(true);
    try {
      const resp = await api.patch("/customer-portal/profile", payload);
      toast.success("Profile updated.");
      if (onSaved) onSaved(resp);
      // Short pause so sonner can land before the modal closes.
      setTimeout(() => { setBusy(false); onClose && onClose(); }, 350);
    } catch (err) {
      setBusy(false);
      // ``api`` throws an Error whose ``.message`` includes the
      // server body for 4xx. Try to parse structured error.
      const detail = (err && (err.detail || err.message)) || "Save failed.";
      const detailStr = typeof detail === "string"
        ? detail
        : (detail && (detail.error_code || detail.message)) || "Save failed.";
      // Known server string patterns → field-level highlight.
      const nextFieldErrs = {};
      if (/confirmation.?mismatch|confirm_current_email/i.test(detailStr)) {
        nextFieldErrs.confirm_current_email =
          "Current email did not match. Please re-enter it exactly.";
      } else if (/email.*(already|exists|taken|in use)/i.test(detailStr)) {
        nextFieldErrs.email = "That email is already in use.";
      } else if (/phone/i.test(detailStr)) {
        nextFieldErrs.phone = detailStr;
      }
      if (Object.keys(nextFieldErrs).length > 0) {
        setFieldErrors(nextFieldErrs);
      } else {
        setServerError(detailStr);
      }
    }
  }

  function _goFullProfile() {
    onClose && onClose();
    navigate("/portal/profile");
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center"
      style={{ background: "rgba(15,23,42,0.55)" }}
      data-testid="portal-edit-profile-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onClose && onClose(); }}
    >
      <div
        className="rounded-2xl shadow-2xl bg-white max-w-md w-[92%] p-6"
        role="dialog"
        aria-labelledby="portal-edit-profile-title"
      >
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            <UserCog className="w-5 h-5" style={{ color: "#1B1F5C" }} />
            <h2
              id="portal-edit-profile-title"
              className="text-lg font-semibold"
              style={{ color: "#0F172A" }}
            >
              Edit profile
            </h2>
          </div>
          <button
            type="button"
            onClick={() => onClose && onClose()}
            className="p-1 rounded-md hover:bg-slate-100"
            aria-label="Close"
            data-testid="portal-edit-profile-close-btn"
          >
            <XIcon className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {serverError ? (
          <div
            className="mb-3 rounded-md border px-3 py-2 text-sm"
            style={{
              borderColor: "#FCA5A5", background: "#FEF2F2",
              color: "#7F1D1D",
            }}
            data-testid="portal-edit-profile-server-error"
          >
            {serverError}
          </div>
        ) : null}

        <form onSubmit={_onSubmit} data-testid="portal-edit-profile-form">
          <_Field
            label="First name"
            testid="portal-edit-profile-first-name"
            value={firstName}
            onChange={setFirstName}
            error={fieldErrors.first_name}
            autoFocus
          />
          <_Field
            label="Last name"
            testid="portal-edit-profile-last-name"
            value={lastName}
            onChange={setLastName}
            error={fieldErrors.last_name}
          />
          <_Field
            label="Phone"
            testid="portal-edit-profile-phone"
            value={phone}
            onChange={setPhone}
            error={fieldErrors.phone}
            inputMode="tel"
          />
          <_Field
            label="Email"
            testid="portal-edit-profile-email"
            value={email}
            onChange={(v) => setEmail(v)}
            error={fieldErrors.email}
            type="email"
          />
          {emailChanged ? (
            <_Field
              label="Confirm current email"
              testid="portal-edit-profile-confirm-current-email"
              value={confirmCurrentEmail}
              onChange={setConfirmCurrentEmail}
              error={fieldErrors.confirm_current_email}
              type="email"
              hint="For your security, re-enter your current email to change it."
            />
          ) : null}

          <div className="flex items-center justify-between mt-5">
            <button
              type="button"
              onClick={_goFullProfile}
              className="text-sm underline"
              style={{ color: "#1B1F5C" }}
              data-testid="portal-edit-profile-full-profile-link"
            >
              Edit full profile →
            </button>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onClose && onClose()}
                className="px-3 py-1.5 rounded-md text-sm border"
                style={{
                  borderColor: "#CBD5E1", color: "#334155",
                  background: "#FFFFFF",
                }}
                data-testid="portal-edit-profile-cancel-btn"
                disabled={busy}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-md text-sm font-semibold text-white hover:brightness-95 active:brightness-90"
                style={{
                  /* TD-73 · Feb-2026 — operator-ruled green parity
                     with the ``Call Now`` CTA
                     (``#16A34A`` from CallNowButton.jsx) so Save
                     and the hero Edit-profile pill read as the
                     same affordance family. Pre-TD-73 this was
                     the portal-navy fill which produced a dark-
                     blue Save beside a muted-white Cancel — the
                     operator-reported low-contrast cluster. */
                  background: "#16A34A",
                  opacity: busy ? 0.7 : 1,
                }}
                data-testid="portal-edit-profile-save-btn"
                disabled={busy}
              >
                {busy ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}


function _Field({ label, testid, value, onChange, error, hint,
                   type = "text", inputMode, autoFocus }) {
  return (
    <label className="block mb-3" data-testid={`${testid}-wrap`}>
      <span className="block text-xs font-medium mb-1"
             style={{ color: "#334155" }}>{label}</span>
      <input
        type={type}
        inputMode={inputMode}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border px-3 py-1.5 text-sm"
        style={{
          borderColor: error ? "#FCA5A5" : "#CBD5E1",
          background: "#FFFFFF",
          color: "#0F172A",
        }}
        data-testid={testid}
      />
      {hint && !error ? (
        <span className="block text-xs mt-1" style={{ color: "#64748B" }}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span
          className="block text-xs mt-1"
          style={{ color: "#B91C1C" }}
          data-testid={`${testid}-error`}
        >
          {error}
        </span>
      ) : null}
    </label>
  );
}
