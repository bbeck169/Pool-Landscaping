/**
 * "My Business Card" — role-agnostic web view of the caller's digital / NFC card.
 *
 * Backs the mobile /(app)/card screen: hits GET /api/card, shows both the
 * company card and (for techs) the personal card with tap-to-call, share,
 * and .vcf download. Anyone signed in can view; only admins can edit the
 * company block, only techs the personal block — the endpoint already
 * enforces that, we just surface the flags.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, api_base } from "@/api";
import { useAuth } from "@/auth";
import { brandGradientCss, colors, font } from "@/theme";
import {
  Phone, Mail, Globe, Star, Copy, Share2, Download, IdCard, Loader2,
} from "lucide-react";

const FALLBACK_COMPANY = {
  name: "Pool & Landscaping of Vistancia",
  region: "Peoria & Vistancia, Arizona",
  tagline: "Your trusted local pool & landscaping pros in Vistancia.",
  phone: "",
  email: "",
  website: "",
  google_review: "",
};

function buildVcard({ name, title, phone, email, website, org }) {
  const lines = [
    "BEGIN:VCARD",
    "VERSION:3.0",
    `FN:${name || ""}`,
    `N:;${name || ""};;;`,
    title ? `TITLE:${title}` : null,
    org ? `ORG:${org}` : null,
    phone ? `TEL;TYPE=CELL:${phone}` : null,
    email ? `EMAIL:${email}` : null,
    website ? `URL:${website}` : null,
    "END:VCARD",
  ].filter(Boolean);
  return lines.join("\n");
}

function downloadVcard(vcf, filename) {
  const blob = new Blob([vcf], { type: "text/vcard;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function ContactRow({ icon: Icon, label, href, testid }) {
  if (!label) return null;
  return (
    <a
      href={href}
      target={href?.startsWith("http") ? "_blank" : undefined}
      rel="noreferrer"
      className="flex items-center gap-3 px-4 py-3 rounded-xl transition hover:brightness-95"
      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
      data-testid={testid}
    >
      <Icon size={18} style={{ color: colors.brand }} />
      <span className="text-sm font-semibold truncate">{label}</span>
    </a>
  );
}

export default function BusinessCard() {
  const { user, loading: authLoading } = useAuth();
  const [state, setState] = useState({ loading: true, data: null, err: null });
  const [mode, setMode] = useState("personal"); // "personal" | "company"
  const [copied, setCopied] = useState("");

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, err: null }));
    try {
      const d = await api.get("/card");
      setState({ loading: false, data: d, err: null });
      // Techs default to their personal card (door-to-door); everyone else the company.
      setMode(d.personal ? "personal" : "company");
    } catch (e) {
      setState({ loading: false, data: null, err: e.message || "Failed to load card" });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const company = state.data?.company || FALLBACK_COMPANY;
  const personal = state.data?.personal;
  const showingPersonal = mode === "personal" && personal;

  const view = useMemo(() => showingPersonal
    ? {
        name: personal.name,
        title: personal.title,
        phone: personal.phone,
        email: personal.email,
        website: company.website,
        org: company.name,
        tagline: null,
      }
    : {
        name: company.name,
        title: company.tagline,
        phone: company.phone,
        email: company.email,
        website: company.website,
        org: company.name,
        tagline: company.region,
      },
    [showingPersonal, personal, company]);

  const vcf = useMemo(() => buildVcard(view), [view]);

  const copy = async (val, key) => {
    try {
      await navigator.clipboard.writeText(val);
      setCopied(key);
      setTimeout(() => setCopied(""), 1500);
    } catch {}
  };

  const share = async () => {
    const shareText = [view.name, view.title, view.phone, view.email, view.website].filter(Boolean).join(" · ");
    if (navigator.share) {
      try { await navigator.share({ title: view.name, text: shareText, url: view.website || undefined }); return; } catch {}
    }
    copy(shareText, "share");
  };

  if (authLoading) return null;
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div
      className="min-h-full p-4 md:p-8 max-w-2xl mx-auto"
      style={{ fontFamily: font.family }}
      data-testid="business-card-page"
    >
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <div
            className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1 rounded-full mb-3"
            style={{ background: brandGradientCss, color: "#fff" }}
          >
            <IdCard size={12} /> NFC-ready
          </div>
          <h1 className="text-3xl md:text-4xl font-bold" style={{ color: colors.onSurface }} data-testid="business-card-title">
            Business Card
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Tap-to-share contact — works with NFC phones and standard .vcf downloads.
          </p>
        </div>
      </div>

      {personal ? (
        <div className="flex gap-2 mb-4" data-testid="card-mode-toggle">
          {[
            { k: "personal", label: "My card" },
            { k: "company", label: "Company card" },
          ].map((t) => {
            const active = mode === t.k;
            return (
              <button
                key={t.k}
                onClick={() => setMode(t.k)}
                className="px-4 py-1.5 rounded-full text-xs font-semibold transition"
                style={{
                  background: active ? brandGradientCss : colors.surface,
                  color: active ? "#fff" : colors.onSurface,
                  border: `1px solid ${active ? "transparent" : colors.border}`,
                }}
                data-testid={`card-mode-${t.k}`}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      ) : null}

      {state.loading ? (
        <div
          className="rounded-2xl p-10 flex items-center justify-center gap-2 text-sm"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}
          data-testid="business-card-loading"
        >
          <Loader2 size={16} className="animate-spin" /> Loading card…
        </div>
      ) : (
        <>
          <div
            className="rounded-3xl overflow-hidden shadow-sm"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="business-card-preview"
          >
            <div
              className="px-6 py-8 text-white"
              style={{ background: brandGradientCss }}
            >
              <div className="text-[11px] uppercase tracking-widest opacity-90 mb-1">
                {showingPersonal ? "Your rep" : "Company"}
              </div>
              <div className="text-2xl font-bold" data-testid="card-name">{view.name}</div>
              {view.title ? (
                <div className="text-sm opacity-95 mt-1" data-testid="card-title">{view.title}</div>
              ) : null}
              {view.tagline ? (
                <div className="text-xs opacity-80 mt-2" data-testid="card-tagline">{view.tagline}</div>
              ) : null}
            </div>
            <div className="p-4 space-y-2">
              <ContactRow icon={Phone} label={view.phone} href={view.phone ? `tel:${view.phone}` : undefined} testid="card-phone" />
              <ContactRow icon={Mail} label={view.email} href={view.email ? `mailto:${view.email}` : undefined} testid="card-email" />
              <ContactRow icon={Globe} label={view.website?.replace(/^https?:\/\//, "")} href={view.website} testid="card-website" />
              {!showingPersonal && company.google_review ? (
                <ContactRow icon={Star} label="Leave a Google review" href={company.google_review} testid="card-review" />
              ) : null}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-4">
            <button
              onClick={() => downloadVcard(vcf, `${(view.name || "card").replace(/\s+/g, "_")}.vcf`)}
              className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-sm font-semibold transition hover:brightness-95"
              style={{ background: brandGradientCss, color: "#fff" }}
              data-testid="card-download-vcf"
            >
              <Download size={14} /> Save contact
            </button>
            <button
              onClick={share}
              className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-sm font-semibold transition hover:brightness-95"
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
              data-testid="card-share"
            >
              <Share2 size={14} /> {copied === "share" ? "Copied" : "Share"}
            </button>
            <button
              onClick={() => copy(vcf, "vcf")}
              className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-sm font-semibold transition hover:brightness-95"
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
              data-testid="card-copy-vcf"
            >
              <Copy size={14} /> {copied === "vcf" ? "Copied vCard" : "Copy vCard"}
            </button>
          </div>

          {state.data?.can_edit_company && !showingPersonal ? (
            <p className="text-xs mt-4" style={{ color: colors.muted }} data-testid="card-edit-hint">
              Admins can edit the company card from the mobile app (Card screen) — the API endpoint is <code>PUT /api/card/company</code>.
            </p>
          ) : null}
          {state.data?.can_edit_personal && showingPersonal ? (
            <p className="text-xs mt-4" style={{ color: colors.muted }} data-testid="card-edit-hint">
              Edit your title/phone/email from the mobile Card screen — the API endpoint is <code>PUT /api/card/personal</code>.
            </p>
          ) : null}

          {state.err ? (
            <div className="mt-4 p-3 rounded-xl text-xs" style={{ backgroundColor: "#FEE2E2", color: colors.error }} data-testid="card-error">
              {state.err}
            </div>
          ) : null}
        </>
      )}

      <div className="mt-6 text-[11px]" style={{ color: colors.muted }}>
        Endpoint: <code>{api_base()}/card</code> · works with an NFC tap-to-share device.
      </div>
    </div>
  );
}
