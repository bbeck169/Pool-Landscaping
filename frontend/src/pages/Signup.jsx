import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth";
import { brandGradientCss, colors, font } from "@/theme";

export default function Signup() {
  const navigate = useNavigate();
  const { signup } = useAuth();
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    phone: "",
    address: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const onSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await signup({
        ...form,
        email: form.email.trim().toLowerCase(),
      });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message || "Signup failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center px-6 py-10"
      style={{ fontFamily: font.family, backgroundColor: colors.surfaceSecondary }}
      data-testid="signup-page"
    >
      <div
        className="w-full max-w-md rounded-2xl p-8"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <div className="flex items-center gap-3 mb-6">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold"
            style={{ background: brandGradientCss }}
          >
            ~
          </div>
          <div className="font-semibold text-lg" style={{ color: colors.onSurface }}>
            Pool &amp; Landscaping
            <div className="text-xs font-normal" style={{ color: colors.muted }}>
              Create your customer account
            </div>
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-3" data-testid="signup-form">
          {[
            { k: "name", label: "FULL NAME", type: "text", required: true },
            { k: "email", label: "EMAIL", type: "email", required: true },
            { k: "password", label: "PASSWORD", type: "password", required: true },
            { k: "phone", label: "PHONE", type: "tel" },
            { k: "address", label: "ADDRESS", type: "text" },
          ].map((f) => (
            <div key={f.k}>
              <label
                htmlFor={f.k}
                className="text-xs font-semibold tracking-wide mb-1 block"
                style={{ color: colors.onSurfaceSecondary }}
              >
                {f.label}
              </label>
              <input
                id={f.k}
                type={f.type}
                required={f.required}
                value={form[f.k]}
                onChange={set(f.k)}
                className="w-full px-4 py-3 rounded-xl outline-none focus:ring-2"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid={`signup-${f.k}-input`}
              />
            </div>
          ))}

          <p className="text-xs mt-1" style={{ color: colors.muted }}>
            Password must be at least 8 characters and include upper, lower, and a
            number.
          </p>

          {error && (
            <div
              className="text-sm px-3 py-2 rounded-lg"
              style={{ backgroundColor: "#FEE2E2", color: colors.error }}
              data-testid="signup-error"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full py-3 rounded-xl text-white font-semibold text-base transition active:scale-[0.99] disabled:opacity-60"
            style={{ background: brandGradientCss }}
            data-testid="signup-submit-button"
          >
            {submitting ? "Creating account…" : "Create account →"}
          </button>
        </form>

        <p
          className="mt-6 text-sm text-center"
          style={{ color: colors.onSurfaceSecondary }}
        >
          Already have an account?{" "}
          <Link
            to="/portal/login"
            className="font-semibold"
            style={{ color: colors.brand }}
            data-testid="signup-goto-login"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
