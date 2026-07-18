import React, { useEffect, useRef, useState } from "react";
import { useParams } from 'react-router-dom';
import SignatureCanvas from "react-signature-canvas";
import { colors, brandGradientCss } from "@/theme";
import { CheckCircle2, Download, RotateCcw } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL;

const Card = ({ children, className = "", testId }) => (
  <div className={"rounded-2xl " + className}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);

export default function PortalSignPage() {
  const { token } = useParams();
  const [meta, setMeta] = useState(null);
  const [name, setName] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [signedNow, setSignedNow] = useState(false);
  const padRef = useRef(null);

  useEffect(() => {
    fetch(`${BASE}/api/public/sign/${token}`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => { setMeta(d); if (d.signer_name) setName(d.signer_name); })
      .catch(() => setError("Signature request not found or expired."));
  }, [token]);

  const clear = () => padRef.current?.clear();

  const submit = async () => {
    if (!name.trim()) return setError("Please type your name.");
    if (!consent) return setError("Please accept the e-signature consent.");
    if (padRef.current?.isEmpty()) return setError("Please draw your signature.");
    setError("");
    setSubmitting(true);
    try {
      const svg = padRef.current.getTrimmedCanvas().toDataURL("image/png");
      const r = await fetch(`${BASE}/api/public/sign/${token}/submit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signer_name: name.trim(), signature_svg: svg }),
      });
      if (!r.ok) throw new Error("submit failed");
      setSignedNow(true);
    } catch (e) {
      setError("Could not submit signature. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (error && !meta) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6" data-testid="sign-error">
        <Card className="p-8 max-w-md text-center">
          <div className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>Not available</div>
          <div className="text-sm" style={{ color: colors.muted }}>{error}</div>
        </Card>
      </div>
    );
  }
  if (!meta) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  const alreadySigned = meta.signed || signedNow;

  return (
    <div className="min-h-screen p-4 md:p-8" style={{ backgroundColor: colors.surfaceSecondary }}
         data-testid="portal-sign-page">
      <div className="max-w-3xl mx-auto">
        <div className="mb-4 text-xs uppercase tracking-wide" style={{ color: colors.muted }}>Pool & Landscaping</div>

        {alreadySigned ? (
          <Card className="p-8 text-center mb-4" testId="sign-success">
            <CheckCircle2 size={56} className="mx-auto mb-3" style={{ color: "#16A34A" }} />
            <h2 className="text-2xl font-bold mb-2" style={{ color: colors.onSurface }}>
              Signed — thank you!
            </h2>
            <div className="text-sm mb-4" style={{ color: colors.muted }}>
              {meta.doc?.title} was signed {meta.signed_at ? "on " + (meta.signed_at || "").slice(0, 19).replace("T", " ") : "successfully"}.
            </div>
            <a href={`${BASE}/api/public/sign/${token}/pdf`} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-white"
               style={{ background: brandGradientCss }}
               data-testid="sign-download-pdf">
              <Download size={16} /> Download signed PDF
            </a>
          </Card>
        ) : null}

        <Card className="p-5 md:p-6 mb-4" testId="sign-doc-preview">
          <div className="text-xs uppercase tracking-wide mb-1" style={{ color: colors.muted }}>
            {meta.doc?.doc_type === "invoice" ? "Invoice" : "Estimate"}
          </div>
          <h1 className="text-2xl font-bold mb-1" style={{ color: colors.onSurface }}>{meta.doc?.title}</h1>
          <div className="text-sm mb-4" style={{ color: colors.muted }}>
            For: {meta.doc?.customer_name}
          </div>
          <div className="mb-3">
            <div className="grid grid-cols-12 gap-2 px-2 py-1 text-xs font-bold uppercase"
                 style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <div className="col-span-6">Description</div>
              <div className="col-span-2 text-right">Qty</div>
              <div className="col-span-2 text-right">Unit</div>
              <div className="col-span-2 text-right">Total</div>
            </div>
            {(meta.doc?.line_items || []).map((li, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 px-2 py-2 text-sm"
                   style={{ borderBottom: `1px solid ${colors.border}`, color: colors.onSurface }}>
                <div className="col-span-6">{li.description}</div>
                <div className="col-span-2 text-right">{li.quantity}</div>
                <div className="col-span-2 text-right">${Number(li.unit_price).toFixed(2)}</div>
                <div className="col-span-2 text-right font-semibold">${(Number(li.quantity) * Number(li.unit_price)).toFixed(2)}</div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between px-2 py-2 rounded-lg"
               style={{ backgroundColor: colors.surfaceSecondary }}>
            <div className="text-sm font-bold" style={{ color: colors.onSurface }}>Total</div>
            <div className="text-xl font-bold" style={{ color: colors.brand }}>
              ${Number(meta.doc?.total || 0).toFixed(2)}
            </div>
          </div>
          {meta.doc?.terms && (
            <details className="mt-4" data-testid="sign-terms">
              <summary className="text-xs font-semibold cursor-pointer" style={{ color: colors.muted }}>
                Terms &amp; Conditions
              </summary>
              <div className="text-xs mt-2 whitespace-pre-wrap" style={{ color: colors.onSurface }}>
                {meta.doc.terms}
              </div>
            </details>
          )}
        </Card>

        {!alreadySigned && (
          <Card className="p-5 md:p-6" testId="sign-pad-card">
            <h2 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>Sign to accept</h2>

            <label className="text-sm font-semibold block mb-1" style={{ color: colors.onSurface }}>
              Full legal name
            </label>
            <input value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="Jennifer Carson"
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none mb-4"
                   style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}
                   data-testid="sign-name-input" />

            <label className="text-sm font-semibold block mb-1" style={{ color: colors.onSurface }}>
              Signature
            </label>
            <div className="rounded-xl mb-2 relative"
                 style={{ border: `1px dashed ${colors.border}`, backgroundColor: "#fff" }}>
              <SignatureCanvas ref={padRef} penColor="#0284C7"
                canvasProps={{ className: "w-full", style: { height: 180, width: "100%" }, "data-testid": "sign-pad-canvas" }} />
              <button onClick={clear}
                      className="absolute top-2 right-2 flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                      data-testid="sign-pad-clear">
                <RotateCcw size={12} /> Clear
              </button>
            </div>

            <label className="flex items-start gap-2 mb-4 mt-3 cursor-pointer">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
                     data-testid="sign-consent" />
              <span className="text-xs" style={{ color: colors.onSurface }}>
                I agree that this electronic signature has the same legal effect as a handwritten signature.
              </span>
            </label>

            <button onClick={submit} disabled={submitting}
                    className="w-full py-3 rounded-xl font-bold text-white"
                    style={{ background: brandGradientCss, opacity: submitting ? 0.7 : 1 }}
                    data-testid="sign-submit">
              {submitting ? "Signing…" : "Sign now"}
            </button>
            {error && <div className="mt-3 text-sm text-center" style={{ color: colors.error }}>{error}</div>}
          </Card>
        )}
      </div>
    </div>
  );
}
