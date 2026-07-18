/**
 * Phase 4 · Batch A — Signature drawing pad modal.
 *
 * Opens over the fill screen when the user clicks "Sign" on a
 * `signature` field. Uses `react-signature-canvas` (already in
 * package.json). On save, produces a PNG data URL + signer name +
 * ISO timestamp; the parent stores that as the field value.
 */
import React, { useRef, useState, useEffect } from "react";
import SignatureCanvas from "react-signature-canvas";
import { X, Eraser, Check } from "lucide-react";
import { colors, brandGradientCss } from "@/theme";

export default function SignaturePadModal({
  open,
  onClose,
  onSave,
  defaultSignerName = "",
  fieldLabel = "Signature",
}) {
  const sigRef = useRef(null);
  const [signerName, setSignerName] = useState(defaultSignerName);
  const [isEmpty, setIsEmpty] = useState(true);

  useEffect(() => {
    if (open) {
      setSignerName(defaultSignerName);
      setIsEmpty(true);
    }
  }, [open, defaultSignerName]);

  if (!open) return null;

  const clear = () => {
    sigRef.current?.clear();
    setIsEmpty(true);
  };

  const save = () => {
    if (!sigRef.current || sigRef.current.isEmpty()) {
      alert("Please draw your signature before saving.");
      return;
    }
    if (!signerName.trim()) {
      alert("Please enter your name to sign.");
      return;
    }
    // Trim whitespace around the drawing when supported. The alpha
    // build of react-signature-canvas ships a broken `trim-canvas`
    // import on some bundlers, so we fall back to the raw canvas.
    let imageDataUrl;
    try {
      const trimmed = sigRef.current.getTrimmedCanvas();
      imageDataUrl = trimmed.toDataURL("image/png");
    } catch (_e) {
      imageDataUrl = sigRef.current.getCanvas().toDataURL("image/png");
    }
    onSave({
      image_data_url: imageDataUrl,
      signer_name: signerName.trim(),
      signed_at: new Date().toISOString(),
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="signature-pad-modal"
    >
      <div
        className="bg-white rounded-2xl w-full max-w-lg p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        style={{ border: `1px solid ${colors.border}` }}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Sign — {fieldLabel}
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100"
            style={{ color: colors.onSurfaceSecondary }}
            data-testid="signature-pad-close"
            aria-label="Close signature pad"
          >
            <X size={16} />
          </button>
        </div>

        <label className="block text-xs font-bold mb-1" style={{ color: colors.onSurfaceSecondary }}>
          Signer name
        </label>
        <input
          type="text"
          value={signerName}
          onChange={(e) => setSignerName(e.target.value)}
          className="w-full mb-3 px-3 py-2 rounded-lg text-sm"
          style={{ border: `1px solid ${colors.border}` }}
          placeholder="Full name of signer"
          data-testid="signature-pad-name-input"
        />

        <label className="block text-xs font-bold mb-1" style={{ color: colors.onSurfaceSecondary }}>
          Draw your signature below
        </label>
        <div
          className="rounded-xl overflow-hidden mb-2"
          style={{ border: `1px dashed ${colors.borderStrong}`, backgroundColor: "#FAFAFA" }}
          data-testid="signature-pad-canvas-wrap"
        >
          <SignatureCanvas
            ref={sigRef}
            penColor={colors.onSurface}
            onEnd={() => setIsEmpty(false)}
            canvasProps={{
              width: 480,
              height: 180,
              className: "w-full",
              "data-testid": "signature-pad-canvas",
            }}
          />
        </div>
        <div className="text-[11px] mb-4" style={{ color: colors.muted }}>
          Use your mouse, trackpad, or stylus. This drawing will be embedded in the exported PDF.
        </div>

        <div className="flex items-center justify-between gap-2">
          <button
            onClick={clear}
            disabled={isEmpty}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
            data-testid="signature-pad-clear"
          >
            <Eraser size={14} /> Clear
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3 py-2 rounded-xl text-sm font-semibold"
              style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
              data-testid="signature-pad-cancel"
            >
              Cancel
            </button>
            <button
              onClick={save}
              className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white"
              style={{ background: brandGradientCss }}
              data-testid="signature-pad-save"
            >
              <Check size={14} /> Save signature
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
