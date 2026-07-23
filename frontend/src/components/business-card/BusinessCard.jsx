// Feb-2026 · Item 6 — Business Card (digital vCard) widget.
//
// Company-only card rendered on every profile page. Gradient hero,
// contact rows, and three action buttons. Save Contact triggers a
// .vcf download from the tenant API endpoint.
import React from "react";
import { toast } from "sonner";
import {
  Phone, Mail, Globe, Star, Download, Share2, ClipboardCopy, Tag,
} from "lucide-react";
import { api, api_base } from "@/api";
import { colors } from "@/theme";

async function fetchCard() {
  return api.get("/tenants/business-card");
}

async function fetchVcfText() {
  const base = api_base();
  const token = localStorage.getItem("token");
  const r = await fetch(`${base}/tenants/business-card.vcf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.text();
}

function saveVcfBlob(text, filename) {
  const blob = new Blob([text], { type: "text/vcard;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename || "business-card.vcf";
  document.body.appendChild(a); a.click();
  a.remove(); URL.revokeObjectURL(url);
}

export default function BusinessCard({ variant = "full" }) {
  const [card, setCard] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    fetchCard().then(setCard).catch(() => setCard(null));
  }, []);
  if (!card) return null;
  const slug = card.tenant_slug || "business-card";

  const onSave = async () => {
    setBusy(true);
    try {
      const text = await fetchVcfText();
      saveVcfBlob(text, `${slug}.vcf`);
      toast.success("Contact downloaded");
    } catch (e) {
      toast.error(`Download failed: ${e.message || e}`);
    } finally { setBusy(false); }
  };

  const onShare = async () => {
    try {
      const text = await fetchVcfText();
      const blob = new Blob([text], { type: "text/vcard" });
      const file = new File([blob], `${slug}.vcf`, { type: "text/vcard" });
      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({
          title: card.company_name,
          text: card.tagline,
          files: [file],
        });
        return;
      }
      // Fallback: copy the public-ish VCF URL to clipboard.
      const base = api_base();
      await navigator.clipboard.writeText(`${base}/tenants/business-card.vcf`);
      toast.success("Business card URL copied to clipboard");
    } catch (e) {
      toast.error(`Share failed: ${e.message || e}`);
    }
  };

  const onCopy = async () => {
    try {
      const text = await fetchVcfText();
      await navigator.clipboard.writeText(text);
      toast.success("vCard text copied to clipboard");
    } catch (e) {
      toast.error(`Copy failed: ${e.message || e}`);
    }
  };

  const gradient = `linear-gradient(135deg, ${card.gradient_from || "#0EA5E9"} 0%, ${card.gradient_to || "#16A34A"} 100%)`;
  const compact = variant === "compact";

  return (
    <div
      className="rounded-2xl shadow-lg overflow-hidden"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="business-card"
    >
      {/* Gradient hero */}
      <div
        className="px-5 py-5 text-white"
        style={{ background: gradient }}
        data-testid="business-card-hero"
      >
        <div className="flex items-center gap-2 mb-3">
          <span
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
            style={{ backgroundColor: "rgba(255,255,255,0.22)", color: "#fff" }}
            data-testid="business-card-nfc-badge"
          >
            <Tag size={9} /> NFC-ready
          </span>
        </div>
        <div className="text-[10px] font-bold uppercase tracking-widest opacity-80">
          Company
        </div>
        <div className="text-xl md:text-2xl font-bold mt-1"
             data-testid="business-card-company-name">
          {card.company_name}
        </div>
        {!compact ? (
          <>
            <div className="text-sm mt-2 opacity-95"
                 data-testid="business-card-tagline">
              {card.tagline}
            </div>
            {card.service_area ? (
              <div className="text-[11px] mt-2 opacity-80"
                   data-testid="business-card-service-area">
                📍 {card.service_area}
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      {/* Contact rows */}
      <div className="p-4 space-y-2">
        {card.phone ? (
          <Row href={`tel:${card.phone}`} icon={<Phone size={14} />}
               label={card.phone} testId="business-card-phone" />
        ) : null}
        {card.email ? (
          <Row href={`mailto:${card.email}`} icon={<Mail size={14} />}
               label={card.email} testId="business-card-email" />
        ) : null}
        {!compact && card.website_url ? (
          <Row href={card.website_url} icon={<Globe size={14} />}
               label={card.website_url.replace(/^https?:\/\//, "")}
               testId="business-card-website" newTab />
        ) : null}
        {!compact && card.google_review_url ? (
          <Row href={card.google_review_url} icon={<Star size={14} />}
               label="Leave a Google review"
               testId="business-card-review" newTab />
        ) : null}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 px-4 pb-4"
           data-testid="business-card-actions">
        <button
          type="button" onClick={onSave} disabled={busy}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold text-white hover:brightness-95 disabled:opacity-60"
          style={{ backgroundColor: colors.brand }}
          data-testid="business-card-save-btn"
        >
          <Download size={12} /> Save contact
        </button>
        {!compact ? (
          <>
            <button
              type="button" onClick={onShare}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold hover:brightness-95"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="business-card-share-btn"
            >
              <Share2 size={12} /> Share
            </button>
            <button
              type="button" onClick={onCopy}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold hover:brightness-95"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="business-card-copy-btn"
            >
              <ClipboardCopy size={12} /> Copy vCard
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Row({ href, icon, label, testId, newTab = false }) {
  return (
    <a
      href={href}
      target={newTab ? "_blank" : undefined}
      rel={newTab ? "noopener noreferrer" : undefined}
      className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:brightness-95 text-sm"
      style={{
        backgroundColor: colors.surfaceSecondary,
        color: colors.onSurface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testId}
    >
      <span aria-hidden style={{ color: colors.brand }}>{icon}</span>
      <span className="truncate">{label}</span>
    </a>
  );
}
