/**
 * Sprint 3c · Feb-2026 · Feature Marketplace tab.
 *
 * Admin-only SettingsHub tile grid. Four premium add-ons:
 *   - Zillow Data · $49/mo
 *   - SEO Rank Heatmap · $99/mo
 *   - AI Analytics · $49/mo
 *   - AI Copilot · $149/mo
 *
 * Backend:
 *   GET  /api/tenants/mine/feature-marketplace
 *   POST /api/tenants/mine/feature-marketplace/{key}/enable
 *   POST /api/tenants/mine/feature-marketplace/{key}/disable
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Home, Map, TrendingUp, Bot, ShoppingBag,
  CheckCircle2, Clock, XCircle, Loader2,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";


const ICONS = {
  home: Home, map: Map, "trending-up": TrendingUp, bot: Bot,
};


function moneyFormat(cents) {
  if (typeof cents !== "number") return "";
  const d = cents / 100.0;
  return `$${d.toFixed(2).replace(/\.00$/, "")}`;
}

function isoToShortDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US",
      { year: "numeric", month: "short", day: "numeric" });
  } catch { return iso.slice(0, 10); }
}


export default function FeatureMarketplaceSettings() {
  const { user } = useAuth() || {};
  const isAdmin = ["admin", "super_admin"].includes(
    (user?.role || "").toLowerCase(),
  );
  const [features, setFeatures] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const [busy, setBusy] = useState(null);              // feature_key
  const [modal, setModal] = useState(null);            // {kind, feature}

  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/mine/feature-marketplace");
      setFeatures(Array.isArray(r?.features) ? r.features : []);
      setLoadErr("");
    } catch (e) {
      setLoadErr(e?.message || "Failed to load feature marketplace");
    }
  }, []);

  useEffect(() => { if (isAdmin) load(); }, [load, isAdmin]);

  const confirmEnable = (feature) => setModal({ kind: "enable", feature });
  const confirmDisable = (feature) => setModal({ kind: "disable", feature });

  const runEnable = async (feature) => {
    setBusy(feature.feature_key);
    try {
      const r = await api.post(
        `/tenants/mine/feature-marketplace/${feature.feature_key}/enable`,
      );
      toast.success(`${feature.display_name} enabled`);
      await load();
      setModal(null);
      return r;
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.body?.detail;
      const msg = (typeof detail === "object" ? detail?.message : null)
                    || e?.message || `Failed to enable ${feature.display_name}`;
      toast.error(msg);
    } finally {
      setBusy(null);
    }
  };

  const runDisable = async (feature) => {
    setBusy(feature.feature_key);
    try {
      const r = await api.post(
        `/tenants/mine/feature-marketplace/${feature.feature_key}/disable`,
      );
      toast.success(`${feature.display_name} scheduled to cancel`);
      await load();
      setModal(null);
      return r;
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.body?.detail;
      const msg = (typeof detail === "object" ? detail?.message : null)
                    || e?.message || `Failed to disable ${feature.display_name}`;
      toast.error(msg);
    } finally {
      setBusy(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="rounded-2xl p-6"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="feature-marketplace-forbidden">
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Admin access required
        </div>
        <div className="text-xs mt-1" style={{ color: colors.muted }}>
          Only admins can browse and enable premium features.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl p-5 space-y-5"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="feature-marketplace-card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2"
               style={{ color: colors.onSurface }}
               data-testid="feature-marketplace-title">
            <ShoppingBag size={18} style={{ color: colors.brand }} />
            Feature Marketplace
          </h2>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Enable premium add-ons on demand. Enabling charges a
            prorated amount for the remainder of this billing
            cycle; disabling cancels at the end of the current cycle.
          </p>
        </div>
      </div>

      {loadErr ? (
        <div className="rounded-lg px-3 py-2 text-sm"
              style={{ background: "#FEF2F2", color: "#991B1B",
                        border: "1px solid #FECACA" }}
              data-testid="feature-marketplace-error">
          {loadErr}
        </div>
      ) : null}

      {!features && !loadErr ? (
        <div className="text-sm flex items-center gap-2"
              style={{ color: colors.muted }}
              data-testid="feature-marketplace-loading">
          <Loader2 size={14} className="animate-spin" />
          Loading marketplace…
        </div>
      ) : null}

      {features ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4"
              data-testid="feature-tile-grid">
          {features.map((feat) => (
            <FeatureTile
              key={feat.feature_key}
              feature={feat}
              busy={busy === feat.feature_key}
              onEnable={() => confirmEnable(feat)}
              onDisable={() => confirmDisable(feat)}
            />
          ))}
        </div>
      ) : null}

      {/* Enable modal */}
      <Dialog open={modal?.kind === "enable"} onOpenChange={(v) => !v && setModal(null)}>
        <DialogContent data-testid="feature-enable-modal">
          <DialogHeader>
            <DialogTitle>
              Enable {modal?.feature?.display_name}?
            </DialogTitle>
            <DialogDescription>
              You'll be charged a prorated amount immediately for
              the remainder of this billing cycle. From next cycle,
              this add-on renews at{" "}
              <strong>{moneyFormat(modal?.feature?.monthly_price_cents)}/month</strong>.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setModal(null)}
              data-testid="feature-enable-cancel">Cancel</Button>
            <Button
              onClick={() => runEnable(modal.feature)}
              disabled={busy === modal?.feature?.feature_key}
              data-testid="feature-enable-confirm">
              {busy === modal?.feature?.feature_key ? "Enabling…" : "Enable"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Disable modal */}
      <Dialog open={modal?.kind === "disable"} onOpenChange={(v) => !v && setModal(null)}>
        <DialogContent data-testid="feature-disable-modal">
          <DialogHeader>
            <DialogTitle>
              Disable {modal?.feature?.display_name}?
            </DialogTitle>
            <DialogDescription>
              Access continues until the end of the current
              billing cycle. You won't be charged again for this
              add-on unless you re-enable it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setModal(null)}
              data-testid="feature-disable-cancel">Cancel</Button>
            <Button
              variant="destructive"
              onClick={() => runDisable(modal.feature)}
              disabled={busy === modal?.feature?.feature_key}
              data-testid="feature-disable-confirm">
              {busy === modal?.feature?.feature_key ? "Scheduling…" : "Disable"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}


function FeatureTile({ feature, busy, onEnable, onDisable }) {
  const IconComp = ICONS[feature.icon] || ShoppingBag;
  const isActive = feature.availability === "already_enabled"
                    && feature.billing_status === "active";
  const isScheduled = feature.enabled
                    && feature.billing_status === "cancelled_end_of_cycle";
  const notConfigured = feature.availability === "not_configured";

  const pill = (() => {
    if (isScheduled) {
      return { label: `Cancels ${isoToShortDate(feature.cancels_at)}`,
                bg: "#FEF3C7", fg: "#92400E", Icon: Clock };
    }
    if (isActive) {
      return { label: "Enabled", bg: "#DCFCE7", fg: "#166534",
                Icon: CheckCircle2 };
    }
    if (notConfigured) {
      return { label: "Not configured", bg: "#FEE2E2", fg: "#991B1B",
                Icon: XCircle };
    }
    return { label: "Available", bg: "#F3F4F6", fg: "#374151", Icon: null };
  })();

  return (
    <div className="rounded-lg p-4 space-y-3"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid={`feature-tile-${feature.feature_key}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="rounded-lg p-2"
                style={{ background: "rgba(2,132,199,0.08)" }}>
            <IconComp size={18} style={{ color: colors.brand }} />
          </div>
          <div>
            <div className="text-sm font-semibold"
                  style={{ color: colors.onSurface }}
                  data-testid={`feature-tile-title-${feature.feature_key}`}>
              {feature.display_name}
            </div>
            <div className="text-xs" style={{ color: colors.muted }}
                  data-testid={`feature-tile-price-${feature.feature_key}`}>
              {moneyFormat(feature.monthly_price_cents)} / month
            </div>
          </div>
        </div>
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-semibold"
               style={{ background: pill.bg, color: pill.fg }}
               data-testid={`feature-tile-status-${feature.feature_key}`}>
          {pill.Icon ? <pill.Icon size={11} /> : null}
          {pill.label}
        </span>
      </div>
      <p className="text-xs" style={{ color: colors.muted }}>
        {feature.description}
      </p>
      <div className="flex items-center justify-end gap-2 pt-1">
        {notConfigured ? (
          <button
            type="button"
            disabled
            title="Contact support to enable this add-on."
            className="px-3 py-1.5 rounded-lg text-xs font-bold cursor-not-allowed"
            style={{ background: "#E5E7EB", color: "#9CA3AF" }}
            data-testid={`feature-tile-button-${feature.feature_key}`}
          >
            Not configured
          </button>
        ) : isActive || isScheduled ? (
          <button
            type="button"
            onClick={onDisable}
            disabled={busy || isScheduled}
            className="px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{ background: isScheduled ? "#E5E7EB" : "#FEE2E2",
                      color: isScheduled ? "#6B7280" : "#991B1B",
                      opacity: busy ? 0.6 : 1 }}
            data-testid={`feature-tile-button-${feature.feature_key}`}
          >
            {isScheduled ? "Scheduled" : "Disable"}
          </button>
        ) : (
          <button
            type="button"
            onClick={onEnable}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{ background: colors.brand, color: "#fff",
                      opacity: busy ? 0.6 : 1 }}
            data-testid={`feature-tile-button-${feature.feature_key}`}
          >
            Enable
          </button>
        )}
      </div>
    </div>
  );
}
