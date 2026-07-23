/**
 * Phase 10 · Feb 2026 — Customer portal referrals page.
 *
 * Landing at ``/portal/referrals`` — shows the customer's own referral
 * code (with tap-to-copy + Share), current credit balance, and the
 * paginated referral + ledger list. Read-only.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  Copy, Share2, CheckCircle2, Phone, ChevronDown, Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";

const STATUS_PILL = {
  pending_conversion: { label: "Waiting for signup", bg: "#F4F4F5", fg: "#52525B" },
  pending_paid_window: { label: "Paid — waiting", bg: "#FFEDD5", fg: "#9A3412" },
  credited: { label: "Credited", bg: "#DCFCE7", fg: "#166534" },
  voided: { label: "Voided", bg: "#F4F4F5", fg: "#71717A" },
};

function fmtDollars(cents) {
  return `$${((cents || 0) / 100).toFixed(2)}`;
}
function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"}); }
  catch { return String(iso).slice(0, 10); }
}
function daysUntil(iso) {
  if (!iso) return null;
  try {
    const ms = new Date(iso).getTime() - Date.now();
    return Math.max(0, Math.ceil(ms / 86_400_000));
  } catch { return null; }
}

export default function PortalReferralsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [showAllLedger, setShowAllLedger] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/referrals/me");
      setData(res);
    } catch (e) {
      toast.error(e.message || "Failed to load referrals");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading || !data) {
    return (
      <div className="min-h-screen bg-zinc-50 flex items-center justify-center">
        <Sparkles className="w-6 h-6 animate-pulse text-zinc-400" />
      </div>
    );
  }

  const code = data.referral_code || "—";
  const balance = data.credits_balance_cents || 0;
  const referrals = data.referrals || [];
  const ledger = data.ledger || [];
  const displayLedger = showAllLedger ? ledger : ledger.slice(0, 20);
  const shareUrl = data.share_url ||
    `${window.location.origin}/leads/new?ref=${encodeURIComponent(code)}`;

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      toast.success("Referral code copied");
    } catch {
      toast.error("Copy failed");
    }
  }

  async function share() {
    const shareData = {
      title: "Get $25 off your first pool service",
      text: `Sign up using my referral code ${code} for $25 off!`,
      url: shareUrl,
    };
    if (navigator.share) {
      try { await navigator.share(shareData); return; } catch {}
    }
    // fallback — copy the share URL.
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast.success("Referral link copied — share it anywhere");
    } catch {
      toast.error("Share failed");
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 pb-24" data-testid="portal-referrals-page">
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
          Refer & earn
        </h1>
        <p className="text-sm text-zinc-500 -mt-2">
          Refer & Earn $25 — after your friend pays for 30 days.
        </p>

        {/* Referral code card */}
        <div className="rounded-2xl bg-white border border-zinc-200 p-5 shadow-sm">
          <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
            Your referral code
          </div>
          <div className="flex items-center gap-3">
            <div className="flex-1 font-mono text-3xl font-bold tracking-wider text-zinc-900"
                 data-testid="portal-ref-code">
              {code}
            </div>
            <button onClick={copyCode}
                    data-testid="portal-ref-copy-btn"
                    className="p-2.5 rounded-lg border border-zinc-200 hover:bg-zinc-50 text-zinc-700">
              {copied ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
            </button>
            <button onClick={share}
                    data-testid="portal-ref-share-btn"
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800">
              <Share2 className="w-4 h-4" />
              Share
            </button>
          </div>
        </div>

        {/* Balance card */}
        <div className="rounded-2xl bg-white border border-zinc-200 p-5 shadow-sm">
          <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
            Credit balance
          </div>
          <div className="text-4xl font-semibold text-zinc-900"
               data-testid="portal-ref-balance">
            {fmtDollars(balance)}
          </div>
          <div className="mt-1 text-sm text-zinc-500">
            Auto-applied to your next invoice.
          </div>
        </div>

        {/* Referrals list */}
        <div className="rounded-2xl bg-white border border-zinc-200 p-5 shadow-sm">
          <div className="text-xs uppercase tracking-wide text-zinc-500 mb-3">
            Your referrals ({referrals.length})
          </div>
          {referrals.length === 0 && (
            <div className="text-sm text-zinc-400 py-8 text-center"
                 data-testid="portal-ref-empty">
              No referrals yet. Share your code to get started.
            </div>
          )}
          <div className="space-y-2">
            {referrals.map((r) => {
              const pill = STATUS_PILL[r.status] || STATUS_PILL.pending_conversion;
              const daysLeft = r.status === "pending_paid_window"
                ? daysUntil(r.eligible_at) : null;
              const label = (r.friend_first_name || "").trim()
                ? `${r.friend_first_name} ${(r.friend_last_initial || "").toUpperCase()}.`
                : "New friend";
              return (
                <div key={r.id}
                     data-testid={`portal-ref-row-${r.id}`}
                     className={`flex items-center justify-between rounded-lg border border-zinc-100 px-3 py-2 ${
                       r.status === "voided" ? "opacity-60" : ""
                     }`}>
                  <div>
                    <div className={`text-sm font-medium text-zinc-900 ${
                                       r.status === "voided" ? "line-through" : ""}`}>
                      {label}
                    </div>
                    <div className="text-xs text-zinc-500">
                      {r.status === "credited" && `Credited ${fmtDate(r.credited_at)}`}
                      {r.status === "pending_paid_window" && (daysLeft != null
                        ? `Paid — ${daysLeft} day${daysLeft === 1 ? "" : "s"} until eligible`
                        : "Paid — waiting for the 30-day window")}
                      {r.status === "pending_conversion" && "Signed up — waiting for first paid invoice"}
                      {r.status === "voided" && (r.voided_reason
                        ? `Voided (${r.voided_reason})` : "Voided")}
                    </div>
                  </div>
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                        style={{ background: pill.bg, color: pill.fg }}
                        title={r.voided_reason || ""}>
                    {pill.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Credit ledger */}
        <div className="rounded-2xl bg-white border border-zinc-200 p-5 shadow-sm">
          <div className="text-xs uppercase tracking-wide text-zinc-500 mb-3">
            Credit history
          </div>
          {displayLedger.length === 0 && (
            <div className="text-sm text-zinc-400 py-6 text-center">
              No credit activity yet.
            </div>
          )}
          <div className="space-y-1">
            {displayLedger.map((l, i) => {
              const delta = l.delta_cents != null
                ? (l.delta_cents / 100)
                : (parseFloat(l.delta) || 0);
              const positive = delta >= 0;
              return (
                <div key={l.id || i}
                     className="flex items-center justify-between px-2 py-2 border-b border-zinc-50 last:border-0 text-sm">
                  <div className="min-w-0">
                    <div className="text-zinc-900 truncate">{l.note || l.source}</div>
                    <div className="text-xs text-zinc-400">{fmtDate(l.created_at)}</div>
                  </div>
                  <div className={`font-semibold ${
                    positive ? "text-green-700" : "text-zinc-700"}`}>
                    {positive ? "+" : "−"}${Math.abs(delta).toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>
          {ledger.length > 20 && !showAllLedger && (
            <button onClick={() => setShowAllLedger(true)}
                    data-testid="portal-ref-ledger-more"
                    className="mt-3 w-full inline-flex items-center justify-center gap-1 text-sm text-zinc-500 hover:text-zinc-900">
              <ChevronDown className="w-4 h-4" />
              Load {ledger.length - 20} more
            </button>
          )}
        </div>

        {/* Call CTA */}
        {data.support_phone_number && (
          <a href={`tel:${data.support_phone_number}`}
             data-testid="portal-ref-call-btn"
             className="block w-full text-center px-4 py-3 rounded-xl bg-blue-600 text-white font-semibold text-base hover:bg-blue-700 transition">
            <Phone className="inline w-5 h-5 mr-2 -mt-0.5" />
            Call {data.support_phone_number}
          </a>
        )}
      </div>
    </div>
  );
}
