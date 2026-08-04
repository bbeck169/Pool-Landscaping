// Feb-2026 · Slice G2 · Widget demo mount page.
// Loads the chat widget script for a specific ``key`` (defaults to
// the aquaterra demo public key). Reused by the admin
// ``/settings/tenant`` live-preview iframe and by manual QA.
//
// The widget bundle attaches to <body>, so this page just needs to
// exist at ``/widget-demo`` and inject the <script> once.
import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;

export default function WidgetDemoPage() {
  const [params] = useSearchParams();
  const [key, setKey] = useState(params.get("key") || params.get("tenant_key") || "");
  const [formId] = useState(params.get("form_id") || "");
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      let widgetKey = key;
      if (!widgetKey) {
        // Fetch the demo tenant's key so previews work without a
        // signed-in admin session (the widget config endpoint is
        // widget-auth-gated, we can't call it here).
        try {
          const r = await axios.get(`${API}/api/tenants/mine/widget-config`);
          if (!cancelled) {
            widgetKey = r.data.public_widget_key;
            setKey(widgetKey);
          }
        } catch (_e) {
          if (!cancelled) setStatus("no-key");
          return;
        }
      }
      if (!widgetKey) return;
      // Guard against double-mount on hot-reload.
      const testId = formId ? "widget-demo-form-script" : "widget-demo-chat-script";
      const existing = document.querySelector(`script[data-testid="${testId}"]`);
      if (existing) existing.remove();
      const script = document.createElement("script");
      script.async = true;
      script.defer = true;
      script.dataset.testid = testId;
      script.dataset.widgetKey = widgetKey;
      if (formId) {
        script.dataset.formId = formId;
        script.src = `${window.location.origin}/widget/form.js`;
      } else {
        script.src = `${window.location.origin}/widget/chat.js`;
      }
      document.body.appendChild(script);
      if (!cancelled) setStatus("mounted");
    }
    boot();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formId]);

  return (
    <div
      data-testid="widget-demo-page"
      style={{
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        color: "#0F172A",
        padding: "40px 24px",
        maxWidth: 720,
        margin: "0 auto",
        minHeight: "100vh",
        background:
          "linear-gradient(180deg, #F8FAFC 0%, #E2E8F0 100%)",
      }}
    >
      <h1
        style={{
          fontSize: 22,
          fontWeight: 700,
          marginBottom: 8,
        }}
        data-testid="widget-demo-title"
      >
        {formId ? "Form preview" : "Chat widget preview"}
      </h1>
      <p
        style={{ fontSize: 14, color: "#475569", marginBottom: 24 }}
        data-testid="widget-demo-subtitle"
      >
        This page renders exactly what your website visitors will see.
        {status === "mounted"
          ? formId
            ? " The embedded form is below."
            : " Click the chat bubble in the bottom-right corner."
          : status === "no-key"
          ? " No widget key found — sign in as admin and try again."
          : " Loading…"}
      </p>
      <div
        data-form-mount
        data-testid="widget-demo-form-mount"
        style={{ marginTop: 20 }}
      />
    </div>
  );
}
