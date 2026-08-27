import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useSearchParams } from "react-router-dom";
import { Check, CheckCircle2, Printer, FileText } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

// Feb 2026 · Two service lines → two ToS docs. ``pool`` is the
// backward-compat default (URL param absent → pool). ``service``
// query param persists selection across reloads + shareable links.
const TOS_TABS = [
  {
    key: "pool",
    label: "Pool",
    slug: "terms-of-service-pool-maintenance",
    testid: "id-tos-toggle-pool",
    bodyTestid: "id-tos-body-pool",
  },
  {
    key: "landscaping",
    label: "Landscaping",
    slug: "terms-of-service-landscaping",
    testid: "id-tos-toggle-landscaping",
    bodyTestid: "id-tos-body-landscaping",
  },
];

/**
 * /portal/terms — customer-facing Terms of Service view.
 *
 * Two documents (Pool + Landscaping) live in parallel. The toggle
 * at top switches which is displayed. Each doc has its own version
 * + ack — customers with both service lines will need to ack both.
 */
export default function PortalTerms() {
  const [params, setParams] = useSearchParams();
  const initial = TOS_TABS.find((t) => t.key === params.get("service"))?.key
    || "pool";
  const [activeKey, setActiveKey] = useState(initial);
  const [docs, setDocs] = useState({});  // { pool: doc, landscaping: doc }
  const [acks, setAcks] = useState({});   // { pool: ack, landscaping: ack }
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const activeTab = TOS_TABS.find((t) => t.key === activeKey) || TOS_TABS[0];
  const doc = docs[activeKey];
  const ack = acks[activeKey] || { acknowledged: false, current_version: null };
  // Feb 2026 · Item 2 — both-agreements-complete indicator. True when
  // BOTH docs have been fetched, BOTH acks say acknowledged, AND both
  // acks are at the DOC's current_version (so a version bump on
  // either doc turns the indicator back off until the customer re-
  // acks). Guards against stale acks flashing green after a legal
  // update.
  const bothAcked = TOS_TABS.every((t) => {
    const a = acks[t.key];
    const d = docs[t.key];
    return a && d
      && a.acknowledged === true
      && a.current_version != null
      && a.current_version === d.version;
  });

  useEffect(() => {
    // Fetch both docs + acks in parallel so the toggle switches
    // instantly without a fresh network round-trip.
    for (const t of TOS_TABS) {
      api.get(`/legal/${t.slug}`)
        .then((d) => setDocs((prev) => ({ ...prev, [t.key]: d })))
        .catch(() =>
          setDocs((prev) => ({ ...prev, [t.key]: null })),
        );
      api.get(`/portal/terms/status?slug=${t.slug}`)
        .then((s) => setAcks((prev) => ({ ...prev, [t.key]: s })))
        .catch(() => {});
    }
  }, []);

  const switchTab = (key) => {
    setActiveKey(key);
    // Keep the URL in sync so page reload / shared link → same tab.
    const next = new URLSearchParams(params);
    next.set("service", key);
    setParams(next, { replace: true });
    setError("");
  };

  const agree = async () => {
    if (!doc) return;
    setSaving(true);
    setError("");
    try {
      await api.post("/portal/terms/acknowledge", {
        slug: activeTab.slug, version: doc.version,
      });
      const s = await api.get(`/portal/terms/status?slug=${activeTab.slug}`);
      setAcks((prev) => ({ ...prev, [activeKey]: s }));
    } catch (e) {
      setError(e?.message || "Could not record your acknowledgement. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  if (!doc) {
    return (
      <div className="max-w-3xl mx-auto p-6" data-testid="portal-terms-loading">
        <div className="animate-pulse h-40 rounded-2xl" style={{ backgroundColor: colors.surfaceTertiary }} />
      </div>
    );
  }

  return (
    <div className="w-full max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6 tos-print-root"
         data-testid="portal-terms-page">
      <style>{`
        @media print {
          .tos-print-hide { display: none !important; }
          .tos-print-root { max-width: none !important; padding: 0 !important; }
          .tos-body { border: none !important; box-shadow: none !important; padding: 0 !important; }
          body { background: #fff !important; }
        }
        /* Feb 2026 · Belt-and-suspenders wrap safety — some ToS
           lines carry long slugs (URL fragments, code spans) that
           would overflow a narrow modal or sidebar-constrained
           layout without ``overflow-wrap: anywhere``. Applied only
           to the ToS body so we don't fight the wider layout. */
        .tos-body-copy { overflow-wrap: anywhere; word-break: break-word; }
      `}</style>

      {/* Feb 2026 · Service segmented toggle. URL-persisted so a
          printed / bookmarked link opens the same tab. Both-agreements
          complete indicator (Item 2) renders to the right when both
          docs are acked at their current version. */}
      <div className="flex flex-wrap items-center gap-3 mb-4 tos-print-hide">
        <div
          className="inline-flex rounded-lg overflow-hidden"
          role="tablist"
          aria-label="Terms of Service — select service line"
          data-testid="id-tos-service-toggle"
          style={{ border: `1px solid ${colors.border}` }}
        >
          {TOS_TABS.map((t) => {
            const selected = t.key === activeKey;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => switchTab(t.key)}
                className="px-4 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2"
                style={{
                  backgroundColor: selected ? colors.brand : colors.surface,
                  color: selected ? "#fff" : colors.onSurface,
                }}
                data-testid={t.testid}
              >
                {t.label}
              </button>
            );
          })}
        </div>
        {bothAcked ? (
          <span
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
            style={{
              background: "#DCFCE7",
              color: "#166534",
              border: "1px solid #86EFAC",
            }}
            data-testid="id-tos-both-complete"
            title="You have acknowledged both the Pool and Landscaping Terms of Service at their current version"
          >
            <CheckCircle2 size={14} strokeWidth={2.5} />
            Both agreements complete
          </span>
        ) : null}
      </div>

      <div className="rounded-2xl p-6 mb-4 tos-body"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-start justify-between flex-wrap gap-3 mb-3 tos-print-hide">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center"
                 style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
              <FileText size={20} />
            </div>
            <div>
              <div className="text-xs uppercase font-semibold tracking-wide" style={{ color: colors.muted }}>
                Legal · {activeTab.label}
              </div>
              <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
                {doc.title}
              </h1>
            </div>
          </div>
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg hover:brightness-95"
            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid="tos-print">
            <Printer size={13} /> Print
          </button>
        </div>

        <div className="text-xs flex flex-wrap gap-x-4 gap-y-1 mb-6 tos-print-hide"
             style={{ color: colors.muted }}>
          <span>Effective: <b style={{ color: colors.onSurface }}>{doc.effective_date || "—"}</b></span>
          <span>Last updated: <b style={{ color: colors.onSurface }}>{(doc.updated_at || "").slice(0, 10)}</b></span>
          <span className="px-2 py-0.5 rounded-md text-xs font-bold"
                style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
            v{doc.version}
          </span>
        </div>

        <article
          className="prose prose-sm max-w-none w-full tos-body-copy"
          data-testid={activeTab.bodyTestid}
          style={{ color: colors.onSurface, lineHeight: 1.65 }}
        >
          <MarkdownBody source={doc.body_markdown || ""} />
        </article>
      </div>

      <div className="rounded-2xl p-5 mb-4 tos-print-hide"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        {ack.acknowledged ? (
          <div className="flex items-center gap-3" data-testid="tos-acknowledged">
            <div className="w-10 h-10 rounded-full flex items-center justify-center"
                 style={{ backgroundColor: "#DCFCE7", color: "#16A34A" }}>
              <Check size={18} />
            </div>
            <div>
              <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>
                You have acknowledged this version.
              </div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                Acked {(ack.acked_at || "").slice(0, 10)} · v{ack.current_version}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="text-sm" style={{ color: colors.onSurface }}>
              By clicking the button you acknowledge you have read and agree to the terms above.
            </div>
            <button
              onClick={agree}
              disabled={saving}
              className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="tos-agree-btn">
              {saving ? "Recording…" : "I have read and agree"}
            </button>
          </div>
        )}
        {error ? (
          <div
            className="mt-3 text-sm rounded-lg px-3 py-2"
            style={{
              backgroundColor: "#FEF3C7",
              color: "#92400E",
              border: "1px solid #FDE68A",
            }}
            data-testid="tos-agree-error"
          >
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MarkdownBody({ source }) {
  return (
    <ReactMarkdown
      components={{
        h2: ({ node, ...props }) => (
          <h2 className="text-2xl font-bold mt-6 mb-3" style={{ color: colors.onSurface }} {...props} />
        ),
        h3: ({ node, ...props }) => (
          <h3 className="text-lg font-bold mt-5 mb-2" style={{ color: colors.onSurface }} {...props} />
        ),
        p: ({ node, ...props }) => (
          <p className="text-sm mb-3" style={{ color: colors.onSurface }} {...props} />
        ),
        ul: ({ node, ...props }) => (
          <ul className="list-disc pl-6 mb-3 space-y-1" style={{ color: colors.onSurface }} {...props} />
        ),
        li: ({ node, ...props }) => (
          <li className="text-sm" {...props} />
        ),
        strong: ({ node, ...props }) => (
          <strong className="font-bold" style={{ color: colors.onSurface }} {...props} />
        ),
        code: ({ node, ...props }) => (
          <code className="px-1 py-0.5 rounded text-xs"
                style={{ backgroundColor: colors.surfaceTertiary, color: colors.brand }}
                {...props} />
        ),
        hr: () => <hr className="my-6" style={{ borderColor: colors.border }} />,
      }}
    >
      {source}
    </ReactMarkdown>
  );
}
