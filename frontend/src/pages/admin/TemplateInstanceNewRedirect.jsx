/**
 * Route helper that creates a new draft template instance from a
 * `?code=<template_code>` query param and redirects to the fill page.
 *
 * Mounted at `/admin/templates/instances/new`.
 */
import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { colors } from "@/theme";
import { createInstance } from "@/api/templates";

export default function TemplateInstanceNewRedirect() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const code = params.get("code");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!code) { setError("Missing ?code=<template_code>."); return; }
      try {
        const inst = await createInstance({ template_code: code });
        if (!cancelled) navigate(`/admin/templates/instances/${inst.id}`, { replace: true });
      } catch (e) {
        if (!cancelled) setError(e.message || "Could not create instance.");
      }
    })();
    return () => { cancelled = true; };
  }, [code, navigate]);

  return (
    <div className="p-8" data-testid="template-instance-new-redirect">
      {error ? (
        <>
          <div className="mb-3 px-3 py-2 rounded-lg text-sm inline-block" style={{ backgroundColor: "#FEE2E2", color: colors.error }}>
            {error}
          </div>
          <div>
            <Link to="/admin/templates" className="text-sm font-semibold" style={{ color: colors.brand }}>
              ← Back to Library
            </Link>
          </div>
        </>
      ) : (
        <div className="text-sm" style={{ color: colors.muted }}>Creating draft…</div>
      )}
    </div>
  );
}
