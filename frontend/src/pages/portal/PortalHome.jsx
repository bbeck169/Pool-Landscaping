import React, { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import {
  Waves,
  Calendar,
  Wrench,
  Receipt,
  FileText,
  MessageSquare,
  ChevronRight,
  AlertCircle,
  Plus,
} from "lucide-react";
import { api } from "@/api";
import { brandGradientCss, colors, money } from "@/theme";
import { useAuth } from "@/auth";
import { PageHeader, Button, Skeleton, Chip, StatusPill } from "@/components/ui-kit";

export default function PortalHome() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/portal/home").then(setData).catch(() => setData({ counts: {} }));
  }, []);

  if (user && user.role !== "customer") return <Navigate to="/" replace />;
  const first = user?.name?.split(" ")[0] || "there";

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-home">
      {/* Hero */}
      <div
        className="rounded-2xl p-6 md:p-8 mb-4 text-white relative overflow-hidden"
        style={{ background: brandGradientCss, minHeight: 180 }}
        data-testid="portal-hero"
      >
        <div
          className="absolute inset-0 opacity-25"
          style={{
            backgroundImage:
              "url(https://images.pexels.com/photos/261101/pexels-photo-261101.jpeg?auto=compress&cs=tinysrgb&w=1200)",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        <div className="relative">
          <p className="text-white/85 text-sm">Welcome back</p>
          <h1 className="text-3xl md:text-4xl font-bold mt-1">Hi, {first} 👋</h1>
          {data ? (
            data.next_visit ? (
              <div className="mt-4 bg-white/15 backdrop-blur rounded-xl p-4">
                <div className="text-xs uppercase tracking-widest opacity-80">Next visit</div>
                <div className="text-lg font-bold mt-0.5">{data.next_visit.title}</div>
                <div className="text-sm opacity-90 mt-1">
                  {data.next_visit.scheduled_date
                    ? new Date(data.next_visit.scheduled_date).toDateString()
                    : "TBD"}{" "}
                  · {data.next_visit.technician_name || "Unassigned"}
                </div>
              </div>
            ) : (
              <p className="text-white/85 mt-3 text-sm">No upcoming visits scheduled.</p>
            )
          ) : (
            <Skeleton style={{ height: 60, backgroundColor: "rgba(255,255,255,0.2)", marginTop: 12 }} />
          )}
        </div>
      </div>

      {/* Alerts */}
      {data ? (
        <div className="grid grid-cols-3 gap-2 mb-4">
          <AlertTile
            testid="alert-overdue"
            label="Overdue"
            value={data.counts.overdue_invoices || 0}
            tone={(data.counts.overdue_invoices || 0) > 0 ? colors.error : colors.muted}
            onClick={() => navigate("/portal/invoices")}
          />
          <AlertTile
            testid="alert-estimates"
            label="Pending estimates"
            value={data.counts.pending_estimates || 0}
            tone={(data.counts.pending_estimates || 0) > 0 ? "#A16207" : colors.muted}
            onClick={() => navigate("/portal/estimates")}
          />
          <AlertTile
            testid="alert-msgs"
            label="Unread messages"
            value={data.counts.unread_messages || 0}
            tone={(data.counts.unread_messages || 0) > 0 ? colors.brand : colors.muted}
            onClick={() => navigate("/portal/messages")}
          />
        </div>
      ) : null}

      {/* Quick actions */}
      <div
        className="rounded-2xl p-5 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="text-xs uppercase font-semibold mb-3" style={{ color: colors.muted }}>
          Quick actions
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <ActionTile icon={Plus} label="Request Service" tone={colors.brand} onClick={() => navigate("/portal/request-service")} testid="qa-request" />
          <ActionTile icon={Receipt} label="Invoices" tone="#A16207" onClick={() => navigate("/portal/invoices")} testid="qa-invoices" />
          <ActionTile icon={FileText} label="Estimates" tone="#4338CA" onClick={() => navigate("/portal/estimates")} testid="qa-estimates" />
          <ActionTile icon={Wrench} label="Payment Method" tone={colors.success} onClick={() => navigate("/portal/payment-method")} testid="qa-pm" />
        </div>
      </div>

      {/* Last visit */}
      {data?.last_visit ? (
        <div
          className="rounded-2xl p-5"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="last-visit-card"
        >
          <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>
            Last visit
          </div>
          <div className="flex items-start gap-3">
            <div
              className="w-11 h-11 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
            >
              <Waves size={18} />
            </div>
            <div className="flex-1">
              <div className="text-base font-semibold" style={{ color: colors.onSurface }}>{data.last_visit.title}</div>
              <div className="text-sm" style={{ color: colors.muted }}>
                {data.last_visit.scheduled_date} · {data.last_visit.technician_name || "—"}
              </div>
              <div className="mt-2"><StatusPill status={data.last_visit.status} /></div>
            </div>
            <button onClick={() => navigate(`/portal/services/${data.last_visit.id}`)}>
              <ChevronRight size={18} color={colors.muted} />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AlertTile({ label, value, tone, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      className="text-left rounded-2xl p-3 transition hover:brightness-95"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      <div className="flex items-center gap-1.5" style={{ color: tone }}>
        <AlertCircle size={13} />
        <span className="text-xs font-semibold">{label}</span>
      </div>
      <div className="text-2xl font-bold mt-1" style={{ color: colors.onSurface }}>{value}</div>
    </button>
  );
}

function ActionTile({ icon: Icon, label, tone, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      className="rounded-xl p-4 text-left transition hover:brightness-95"
      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-2" style={{ backgroundColor: tone + "20", color: tone }}>
        <Icon size={18} />
      </div>
      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{label}</div>
    </button>
  );
}
