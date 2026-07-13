import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { Check, Printer, FileText } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const SLUG = "terms-of-service-pool-maintenance";

/**
 * /portal/terms — customer-facing Terms of Service view.
 * Fetches from /api/legal/{slug}, renders markdown, and lets the customer
 * acknowledge the current version.
 */
export default function PortalTerms() {
  const [doc, setDoc] = useState(null);
  const [ack, setAck] = useState({ acknowledged: false, current_version: null });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get(`/legal/${SLUG}`).then(setDoc).catch(() => setDoc(null));
    api.get(`/portal/terms/status?slug=${SLUG}`).then(setAck).catch(() => {});
  }, []);

  const agree = async () => {
    setSaving(true);
    try {
      await api.post("/portal/terms/acknowledge", { slug: SLUG, version: doc.version });
      const s = await api.get(`/portal/terms/status?slug=${SLUG}`);
      setAck(s);
    } catch (e) {
      // Best-effort; the button just re-enables.
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
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6 tos-print-root"
         data-testid="portal-terms-page">
      <style>{`
        @media print {
          .tos-print-hide { display: none !important; }
          .tos-print-root { max-width: none !important; padding: 0 !important; }
          .tos-body { border: none !important; box-shadow: none !important; padding: 0 !important; }
          body { background: #fff !important; }
        }
      `}</style>

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
                Legal
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

        <article className="prose prose-sm max-w-none" data-testid="tos-content"
                 style={{ color: colors.onSurface, lineHeight: 1.65 }}>
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
