import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { useAuth } from "@/auth";

/**
 * Tenant Picker — shown after login when the user belongs to >1 active tenants.
 * Sets `tenant_slug` in localStorage (which the api.js wrapper attaches as
 * `X-Tenant-Slug` on every request) and reloads the app.
 */
export default function TenantPicker() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get("/tenants/memberships/mine");
        const list = Array.isArray(res) ? res : (res?.memberships || []);
        setRows(list);
        // Auto-skip when only 1 active membership.
        if (list.length <= 1) {
          navigate("/", { replace: true });
        }
      } catch (e) {
        setErr(e?.message || "Failed to load tenants");
      } finally {
        setLoading(false);
      }
    })();
  }, [navigate]);

  const pick = (row) => {
    if (row.slug) {
      localStorage.setItem("tenant_slug", row.slug);
      localStorage.setItem("tenant_name", row.name || row.slug);
      window.location.href = "/";
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-500">
        Loading your tenants…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="w-full max-w-lg bg-white shadow-xl rounded-2xl p-8" data-testid="tenant-picker">
        <h1 className="text-2xl font-semibold text-slate-900">Choose a workspace</h1>
        <p className="text-sm text-slate-500 mt-1">
          Signed in as <span className="font-medium text-slate-700">{user?.email}</span>
        </p>
        {err && <p className="text-red-600 text-sm mt-4">{err}</p>}
        <div className="mt-6 space-y-3">
          {rows.map((r) => (
            <button
              key={r.tenant_id || r.slug}
              onClick={() => pick(r)}
              data-testid={`tenant-picker-option-${r.slug}`}
              className="w-full flex items-center gap-4 rounded-xl border border-slate-200 hover:border-sky-500 hover:bg-sky-50 transition p-4 text-left"
            >
              <span
                className="inline-block w-3 h-10 rounded-full"
                style={{ background: r.brand_primary || "#0284C7" }}
                aria-hidden
              />
              <div className="flex-1">
                <div className="font-medium text-slate-900">{r.name || r.slug}</div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {r.role || "member"} · {r.slug}
                </div>
              </div>
              <span className="text-slate-400">→</span>
            </button>
          ))}
        </div>
        <div className="mt-8 flex justify-between text-sm">
          <button
            onClick={logout}
            className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-semibold shadow-sm text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55"
            data-testid="tenant-picker-logout"
          >
            Sign out
          </button>
          <button
            onClick={() => {
              localStorage.removeItem("tenant_slug");
              navigate("/", { replace: true });
            }}
            className="text-slate-500 hover:text-slate-800"
            data-testid="tenant-picker-skip"
          >
            Use my default workspace
          </button>
        </div>
      </div>
    </div>
  );
}


/**
 * Small chip shown in the app header with a "Switch tenant" link.
 * Only renders when a tenant slug is currently active in localStorage.
 */
export function TenantChip() {
  const navigate = useNavigate();
  const slug = typeof window !== "undefined" ? localStorage.getItem("tenant_slug") : "";
  const name = typeof window !== "undefined" ? localStorage.getItem("tenant_name") : "";
  if (!slug) return null;
  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-100 text-xs text-slate-600"
      data-testid="tenant-chip"
    >
      <span className="w-2 h-2 rounded-full bg-sky-500" aria-hidden />
      <span className="font-medium">{name || slug}</span>
      <button
        onClick={() => navigate("/tenant-picker")}
        className="text-sky-600 hover:text-sky-800 ml-1"
        data-testid="tenant-chip-switch"
      >
        Switch
      </button>
    </div>
  );
}
