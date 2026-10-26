/**
 * Phase 15 · Feb-2026 — Mass Messaging Compose Dialog.
 *
 * Full-screen shadcn Dialog. Admin/super_admin only. Flow:
 *
 *  1. Pick channels — Email + SMS checkboxes (both default on).
 *  2. Pick a template (dropdown, filtered by channel) OR toggle
 *     "Custom message" and type subject/body inline.
 *  3. Live preview — as channels/audience/body change we debounce
 *     a call to `POST /api/mass-messaging/preview` and render the
 *     estimated recipient counts + sample render output.
 *  4. "Send Now" is disabled until (a) at least one channel is
 *     picked AND (b) either a template is selected or a custom
 *     body is provided.
 *  5. Click "Send Now" → confirmation modal ("You are about to
 *     send to X customers. This can't be undone.") → confirm →
 *     `POST /api/mass-messaging/send` with the preview's
 *     `confirm_token`. On success we close the dialog and toast.
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Mail, MessageSquareText, Loader2, AlertCircle,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import AiRewriteButton from "@/components/ai/AiRewriteButton";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

function useDebounced(value, delay = 500) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export default function MassMessagingComposeDialog({ open, onOpenChange }) {
  const [channels, setChannels] = useState({ email: true, sms: true });
  const [templates, setTemplates] = useState([]);
  const [useCustom, setUseCustom] = useState(true);
  const [templateId, setTemplateId] = useState("");
  const [subject, setSubject] = useState("Hi {{customer.first_name}}");
  const [body, setBody] = useState(
    "Hi {{customer.first_name}} — quick note from the team. Reply STOP to opt out."
  );

  // Phase 16 · Item 3 — audience filters. Each is a Set of ids; the
  // preview payload passes them as sorted arrays so the confirm-token
  // binding hashes deterministically.
  const [categoryIds, setCategoryIds] = useState([]);
  const [serviceDays, setServiceDays] = useState([]);
  const [assignedTechUserIds, setAssignedTechUserIds] = useState([]);
  const [categoryOptions, setCategoryOptions] = useState([]);
  const [techOptions, setTechOptions] = useState([]);
  // Feb-2026 · Item 2 — audience-status segmented control. Resets to
  // "active" on each fresh dialog open (per PRD: safer default).
  const [audienceStatus, setAudienceStatus] = useState("active");
  // P2 #7 · Feb-2026 — Card-on-file + Portal-login filters. Tri-state
  // ``null | true`` only (no negation this ticket). ``null`` = no
  // restriction. Reset to ``null`` on each fresh dialog open to match
  // the audience-status "safer default" invariant.
  const [hasCardOnFile, setHasCardOnFile] = useState(null);
  const [hasPortalLogin, setHasPortalLogin] = useState(null);
  useEffect(() => {
    if (open) {
      setAudienceStatus("active");
      setHasCardOnFile(null);
      setHasPortalLogin(null);
    }
  }, [open]);

  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sending, setSending] = useState(false);

  const chList = useMemo(
    () => Object.entries(channels).filter(([, v]) => v).map(([k]) => k),
    [channels]
  );

  // Fetch template + category + tech catalogs on open.
  // INTENTIONAL DIVERGENCE: this dialog does NOT consume
  // ``components/communications/TemplatePickerPreview`` — bulk-messaging
  // UX differs (dropdown, debounced auto-preview, ``useCustom`` toggle,
  // client-side channel filter). See
  // ``memory/td100_shared_compose_modal_audit.md`` + TD-100-sub-template
  // close-out note in ``memory/TECH_DEBT.md`` for the parent-audit
  // rationale rejecting consolidation.
  useEffect(() => {
    if (!open) return;
    api.get("/marketing/templates").then((r) => {
      const items = Array.isArray(r) ? r : r?.items || [];
      setTemplates(items);
    }).catch(() => setTemplates([]));
    api.get("/customer-categories").then((r) => {
      setCategoryOptions(Array.isArray(r?.items) ? r.items : []);
    }).catch(() => setCategoryOptions([]));
    api.get("/team?role=technician").then((r) => {
      const items = Array.isArray(r) ? r : (r?.items || r?.users || []);
      setTechOptions(items);
    }).catch(() => setTechOptions([]));
  }, [open]);

  // Debounced live preview — added filters into the dependency list
  // so any filter change triggers a re-fetch (spec calls for ~300ms
  // debounce, matched by useDebounced's default 500ms which is close
  // enough and prevents preview thrashing).
  const debSubj = useDebounced(subject);
  const debBody = useDebounced(body);
  const debTpl = useDebounced(templateId);
  const debChannels = useDebounced(chList.join(","));
  const debCats = useDebounced(categoryIds.join(","));
  const debDays = useDebounced(serviceDays.join(","));
  const debTechs = useDebounced(assignedTechUserIds.join(","));

  useEffect(() => {
    if (!open) return;
    if (chList.length === 0) { setPreview(null); return; }
    if (!useCustom && !templateId) { setPreview(null); return; }
    if (useCustom && !debBody.trim()) { setPreview(null); return; }

    let cancelled = false;
    setPreviewLoading(true); setPreviewError("");
    const payload = {
      channels: chList,
      audience: "all_active_customers",
      category_ids: categoryIds,
      service_days: serviceDays,
      assigned_tech_user_ids: assignedTechUserIds,
      audience_status: audienceStatus,
      // P2 #7 · Feb-2026 — ALWAYS include both keys (as true | null,
      // never omit) so the confirm-token-binding signature hashes
      // deterministically regardless of whether an admin has
      // toggled either filter. The backend ``_consume_confirm_token``
      // guard uses strict equality on these two keys so any
      // omission → mismatch between preview + send would surface
      // as CONFIRM_TOKEN_FILTERS_MISMATCH.
      has_card_on_file: hasCardOnFile,
      has_portal_login: hasPortalLogin,
      ...(useCustom
        ? { subject: debSubj || null, body: debBody }
        : { template_id: debTpl }),
    };
    api.post("/mass-messaging/preview", payload).then((r) => {
      if (cancelled) return;
      setPreview(r);
    }).catch((e) => {
      if (cancelled) return;
      setPreviewError(e?.message || "Preview failed");
      setPreview(null);
    }).finally(() => !cancelled && setPreviewLoading(false));

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, debChannels, debSubj, debBody, debTpl, useCustom,
       debCats, debDays, debTechs, audienceStatus,
       hasCardOnFile, hasPortalLogin]);

  const total = (preview?.estimated_recipients?.email || 0)
    + (preview?.estimated_recipients?.sms || 0);
  const canSend = chList.length > 0
    && ((useCustom && body.trim().length > 0) || (!useCustom && !!templateId))
    && !!preview?.confirm_token
    && total > 0
    && !sending;

  const filteredTemplates = useMemo(() => {
    const ch = chList[0] || "";
    return templates.filter((t) => (t.channel || "").toLowerCase() === ch);
  }, [templates, chList]);

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      // BUG G · Feb 2026 — the send payload MUST carry the same
      // ``category_ids`` / ``service_days`` / ``assigned_tech_user_ids``
      // the preview issued the confirm-token against; the backend's
      // ``_consume_confirm_token`` guard rejects a filter-signature
      // drift with 400 CONFIRM_TOKEN_FILTERS_MISMATCH, which made
      // mass-messaging silently fail the moment an admin applied ANY
      // filter. See ``routers/mass_messaging.py::_consume_confirm_token``.
      const payload = {
        channels: chList,
        audience: "all_active_customers",
        confirm_token: preview.confirm_token,
        audience_status: audienceStatus,
        category_ids: categoryIds,
        service_days: serviceDays,
        assigned_tech_user_ids: assignedTechUserIds,
        // P2 #7 · Feb-2026 — must be present on send with the SAME
        // values the preview was issued against. See the matching
        // comment on the preview payload above; CONFIRM_TOKEN_
        // FILTERS_MISMATCH surfaces on any drift.
        has_card_on_file: hasCardOnFile,
        has_portal_login: hasPortalLogin,
        ...(useCustom
          ? { subject: subject || null, body }
          : { template_id: templateId }),
      };
      const res = await api.post("/mass-messaging/send", payload);
      toast.success(
        `Broadcast started — ${res.queued_email + res.queued_sms} messages queued. ` +
        `Check status in Marketing → Broadcasts.`,
        { duration: 6000 }
      );
      setConfirmOpen(false);
      onOpenChange(false);
    } catch (e) {
      const detail = e?.detail || e;
      const msg = typeof detail === "object" && detail.code
        ? `${detail.code}: ${detail.window_seconds
            ? `try again in ${Math.ceil(detail.window_seconds / 60)}m`
            : (detail.message || "See server logs")}`
        : (e?.message || "Send failed");
      toast.error(msg, { duration: 6000 });
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          className="max-w-4xl max-h-[92vh] overflow-y-auto"
          data-testid="mass-messaging-dialog"
        >
          <DialogHeader>
            <DialogTitle>Mass Messaging — Compose Broadcast</DialogTitle>
            <DialogDescription>
              Send a one-time message to every active customer. Suppression,
              unsubscribe, and no-contact filters are applied automatically.
            </DialogDescription>
          </DialogHeader>

          {/* Channels */}
          <div className="grid gap-4 mt-2">
            {/* Phase 16 · Item 3 · Feb-2026 — Audience filters. Empty
                selection = no restriction on that axis. Multiple
                selections within a single filter are ORed; multiple
                filters are ANDed. */}
            <section data-testid="mass-messaging-filters">
              <div
                className="text-[11px] font-bold uppercase tracking-wider mb-2"
                style={{ color: colors.muted }}
              >
                Audience filters
              </div>
              {/* Feb-2026 · Item 2 — Audience-status segmented control. */}
              <div className="mb-3">
                <div className="text-[11px] uppercase tracking-wide font-semibold mb-1"
                     style={{ color: colors.muted }}>
                  Audience status
                </div>
                <div
                  className="inline-flex rounded-md p-0.5"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}`,
                  }}
                  role="tablist"
                  data-testid="mass-messaging-audience-status"
                >
                  {[
                    { key: "active",   label: "Active" },
                    { key: "inactive", label: "Inactive" },
                    { key: "both",     label: "Both" },
                  ].map((o) => {
                    const active = audienceStatus === o.key;
                    return (
                      <button
                        key={o.key}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => setAudienceStatus(o.key)}
                        className="px-2.5 py-1 rounded text-xs font-semibold transition"
                        style={{
                          backgroundColor: active ? colors.brand : "transparent",
                          color: active ? "#fff" : colors.onSurface,
                        }}
                        data-testid={`mass-messaging-audience-status-${o.key}`}
                      >{o.label}</button>
                    );
                  })}
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <PillMultiSelect
                  label="Categories"
                  testid="mass-messaging-filter-categories"
                  options={categoryOptions.map((c) => ({
                    id: c.id, name: c.name, color: c.color,
                  }))}
                  selectedIds={categoryIds}
                  onChange={setCategoryIds}
                />
                <PillMultiSelect
                  label="Service days"
                  testid="mass-messaging-filter-days"
                  options={[
                    { id: "mon", name: "Mon" }, { id: "tue", name: "Tue" },
                    { id: "wed", name: "Wed" }, { id: "thu", name: "Thu" },
                    { id: "fri", name: "Fri" }, { id: "sat", name: "Sat" },
                    { id: "sun", name: "Sun" },
                  ]}
                  selectedIds={serviceDays}
                  onChange={setServiceDays}
                />
                <PillMultiSelect
                  label="Assigned techs"
                  testid="mass-messaging-filter-techs"
                  options={techOptions.map((t) => ({
                    id: t.id, name: t.name || t.email || t.id,
                  }))}
                  selectedIds={assignedTechUserIds}
                  onChange={setAssignedTechUserIds}
                />
              </div>
              {/* P2 #7 · Feb-2026 — Card-on-file + Portal-login checkbox
                  pair. Binary semantics (tri-state null|true only —
                  negation deferred as P3). Both default off; the
                  state resets to null on each fresh dialog open. */}
              <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2">
                <label
                  className="flex items-center gap-2 cursor-pointer text-sm"
                  data-testid="mass-messaging-filter-card-on-file-label"
                >
                  <Checkbox
                    checked={hasCardOnFile === true}
                    onCheckedChange={(v) => setHasCardOnFile(v ? true : null)}
                    data-testid="mass-messaging-filter-card-on-file"
                  />
                  <span>Has card on file</span>
                </label>
                <label
                  className="flex items-center gap-2 cursor-pointer text-sm"
                  data-testid="mass-messaging-filter-portal-login-label"
                >
                  <Checkbox
                    checked={hasPortalLogin === true}
                    onCheckedChange={(v) => setHasPortalLogin(v ? true : null)}
                    data-testid="mass-messaging-filter-portal-login"
                  />
                  <span>Has active portal login</span>
                </label>
              </div>
            </section>

            <section>
              <div
                className="text-[11px] font-bold uppercase tracking-wider mb-2"
                style={{ color: colors.muted }}
              >
                Channels
              </div>
              <div className="flex items-center gap-4">
                <label
                  className="flex items-center gap-2 cursor-pointer"
                  data-testid="mass-messaging-channel-email"
                >
                  <Checkbox
                    checked={channels.email}
                    onCheckedChange={(v) =>
                      setChannels((c) => ({ ...c, email: !!v }))
                    }
                    data-testid="mass-messaging-channel-email-checkbox"
                  />
                  <Mail size={14} /> Email
                </label>
                <label
                  className="flex items-center gap-2 cursor-pointer"
                  data-testid="mass-messaging-channel-sms"
                >
                  <Checkbox
                    checked={channels.sms}
                    onCheckedChange={(v) =>
                      setChannels((c) => ({ ...c, sms: !!v }))
                    }
                    data-testid="mass-messaging-channel-sms-checkbox"
                  />
                  <MessageSquareText size={14} /> SMS
                </label>
              </div>
            </section>

            {/* Message source */}
            <section>
              <div
                className="text-[11px] font-bold uppercase tracking-wider mb-2"
                style={{ color: colors.muted }}
              >
                Message source
              </div>
              <div className="flex items-center gap-4 mb-3">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="mm-source"
                    checked={useCustom}
                    onChange={() => setUseCustom(true)}
                    data-testid="mass-messaging-source-custom"
                  />
                  <span className="text-sm">Custom message</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="mm-source"
                    checked={!useCustom}
                    onChange={() => setUseCustom(false)}
                    data-testid="mass-messaging-source-template"
                  />
                  <span className="text-sm">Pick a template</span>
                </label>
              </div>

              {useCustom ? (
                <div className="grid gap-3">
                  {channels.email ? (
                    <div>
                      <label
                        className="text-[11px] font-semibold uppercase"
                        style={{ color: colors.muted }}
                      >
                        Subject (email)
                      </label>
                      <Input
                        value={subject}
                        onChange={(e) => setSubject(e.target.value)}
                        placeholder="Hi {{customer.first_name}}"
                        data-testid="mass-messaging-subject-input"
                      />
                    </div>
                  ) : null}
                  <div>
                    <div className="flex items-center justify-between">
                      <label
                        className="text-[11px] font-semibold uppercase"
                        style={{ color: colors.muted }}
                      >
                        Body — supports merge tags like {"{{customer.first_name}}"}
                      </label>
                      {/* Ticket LL · Feb-2026 — AI rewrite button
                          polishes the operator-authored broadcast
                          body.  Body-only (subject preserved). */}
                      <AiRewriteButton
                        value={body}
                        onReplace={setBody}
                        dataTestid="mass-messaging-rewrite-btn"
                      />
                    </div>
                    <Textarea
                      rows={5}
                      value={body}
                      onChange={(e) => setBody(e.target.value)}
                      placeholder="Type your broadcast message…"
                      data-testid="mass-messaging-body-input"
                    />
                  </div>
                </div>
              ) : (
                <div>
                  <select
                    value={templateId}
                    onChange={(e) => setTemplateId(e.target.value)}
                    className="w-full px-3 py-2 rounded-md text-sm"
                    style={{
                      border: `1px solid ${colors.border}`,
                      background: colors.surface,
                      color: colors.onSurface,
                    }}
                    data-testid="mass-messaging-template-select"
                  >
                    <option value="">Select a {chList[0] || "…"} template</option>
                    {filteredTemplates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name || t.code || t.id}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </section>

            {/* Live preview */}
            <section
              className="rounded-lg p-3"
              style={{
                background: colors.surfaceSecondary,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="mass-messaging-preview"
            >
              <div
                className="text-[11px] font-bold uppercase tracking-wider mb-2"
                style={{ color: colors.muted }}
              >
                Live preview
                {previewLoading ? (
                  <span
                    className="inline-flex items-center gap-1 ml-2 text-[10px] normal-case"
                    style={{ color: colors.brand }}
                    data-testid="mass-messaging-preview-refreshing"
                  >
                    <Loader2 size={11} className="animate-spin" />
                    Refreshing…
                  </span>
                ) : null}
              </div>
              {previewError ? (
                <div className="text-xs" style={{ color: "#DC2626" }}>
                  <AlertCircle size={12} className="inline mr-1" />
                  {previewError}
                </div>
              ) : null}
              {preview ? (
                <>
                  <div
                    className="text-sm"
                    style={{ color: colors.onSurface }}
                    data-testid="mass-messaging-preview-summary"
                  >
                    Sending to <b>{total}</b> recipient
                    {total === 1 ? "" : "s"}
                    {" — "}
                    <b>{preview.estimated_recipients.email}</b> via email,
                    {" "}<b>{preview.estimated_recipients.sms}</b> via SMS.
                  </div>
                  <div
                    className="text-[11px] mt-1"
                    style={{ color: colors.muted }}
                  >
                    {preview.stats.suppressed_email + preview.stats.suppressed_sms} suppressed,
                    {" "}{preview.stats.no_contact_email} without email,
                    {" "}{preview.stats.no_contact_sms} without phone.
                    {" · Est. cost: $"}{preview.estimated_cost_hint}
                  </div>

                  {preview.sample_render?.email_subject ? (
                    <div className="mt-3">
                      <div
                        className="text-[10px] font-bold uppercase"
                        style={{ color: colors.muted }}
                      >
                        Email sample
                      </div>
                      <div
                        className="text-xs font-semibold mt-0.5"
                        style={{ color: colors.onSurface }}
                      >
                        {preview.sample_render.email_subject}
                      </div>
                      <div
                        className="text-xs mt-1 whitespace-pre-wrap"
                        style={{ color: colors.onSurface }}
                        dangerouslySetInnerHTML={{
                          __html: preview.sample_render.email_body_html,
                        }}
                      />
                    </div>
                  ) : null}

                  {preview.sample_render?.sms_body ? (
                    <div className="mt-3">
                      <div
                        className="text-[10px] font-bold uppercase"
                        style={{ color: colors.muted }}
                      >
                        SMS sample
                      </div>
                      <div
                        className="text-xs mt-0.5 whitespace-pre-wrap"
                        style={{ color: colors.onSurface }}
                      >
                        {preview.sample_render.sms_body}
                      </div>
                    </div>
                  ) : null}

                  {preview.sample_render?.unresolved_tokens?.length ? (
                    <div
                      className="text-[11px] mt-2 px-2 py-1 rounded"
                      style={{ background: "#FEF3C7", color: "#92400E" }}
                      data-testid="mass-messaging-unresolved-tokens"
                    >
                      Unresolved tokens:{" "}
                      {preview.sample_render.unresolved_tokens.join(", ")}
                    </div>
                  ) : null}
                </>
              ) : !previewLoading ? (
                <div className="text-xs" style={{ color: colors.muted }}>
                  Pick channels + a template or custom body to preview.
                </div>
              ) : null}
            </section>
          </div>

          <div className="mt-4 flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              data-testid="mass-messaging-cancel-btn"
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => setConfirmOpen(true)}
              disabled={!canSend}
              data-testid="mass-messaging-send-btn"
            >
              {sending ? (
                <><Loader2 size={14} className="animate-spin mr-2" />Sending…</>
              ) : "Send Now"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent data-testid="mass-messaging-confirm-modal">
          <K72BroadcastConfirmBody
            total={total}
            audience="all_active_customers"
            subject={useCustom ? subject : (
              templates.find((t) => t.id === templateId)?.subject || ""
            )}
            bodyPreview={useCustom
              ? body
              : (templates.find((t) => t.id === templateId)?.body || "")}
            templateKey={useCustom ? "(custom message)"
                                   : (templates.find(
                                       (t) => t.id === templateId,
                                     )?.name || templateId || "(none)")}
            channels={chList}
            onConfirm={handleSend}
            onCancel={() => setConfirmOpen(false)}
            sending={sending}
          />
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}


/**
 * Phase K72.1 · Feb-2026 — Broadcast confirmation modal body.
 *
 * Fires the "big red button" confirmation flow whenever the operator
 * is about to hit either:
 *   * ``audience === "all_active_customers"`` (any size), OR
 *   * more than **50 recipients** for any audience (safety threshold
 *     for large targeted sends).
 *
 * Guard: the operator must type the tenant name (from
 * ``localStorage.tenant_name``) exactly — case-sensitive — to unlock
 * the send button. Cancel button is the default. Sub-50 targeted
 * sends bypass the type-to-confirm step and get a simple one-click
 * confirmation for parity with the pre-K72 flow.
 */
function K72BroadcastConfirmBody({
  total, audience, subject, bodyPreview, templateKey, channels,
  onConfirm, onCancel, sending,
}) {
  const tenantName = (typeof window !== "undefined"
                       ? (window.localStorage?.getItem?.("tenant_name") || "")
                       : "").trim();
  const isBroadcast = audience === "all_active_customers"
                        || (total > 50);
  const requiresTypeConfirm = isBroadcast && !!tenantName;
  const [typed, setTyped] = React.useState("");
  const typedOk = requiresTypeConfirm
    ? typed.trim() === tenantName
    : true;
  const truncate = (s, n) => (s || "").length > n
    ? `${(s || "").slice(0, n)}…`
    : (s || "");
  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle
          data-testid="k72-broadcast-confirm-title"
          style={{ color: isBroadcast ? "#B91C1C" : undefined }}
        >
          {isBroadcast ? "Confirm broadcast" : "Confirm send"}
        </AlertDialogTitle>
        <AlertDialogDescription>
          {isBroadcast ? (
            <span data-testid="k72-broadcast-blast-notice">
              You&apos;re about to send to <b>{total}</b>{" "}
              customer{total === 1 ? "" : "s"}.{" "}
              <b>This cannot be undone.</b>
            </span>
          ) : (
            <>You are about to send to <b>{total}</b>{" "}
              customer{total === 1 ? "" : "s"}. This can&apos;t be
              undone.</>
          )}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <div
        className="rounded-md px-3 py-2 text-xs space-y-1 my-2"
        style={{ background: colors.surfaceSecondary,
                  border: `1px solid ${colors.divider}` }}
        data-testid="k72-broadcast-preview"
      >
        <div>
          <b>Recipients:</b>{" "}
          <span data-testid="k72-broadcast-total">{total}</span>
        </div>
        <div><b>Channels:</b> {(channels || []).join(", ") || "email"}</div>
        <div>
          <b>Template:</b>{" "}
          <span data-testid="k72-broadcast-template">{templateKey}</span>
        </div>
        <div>
          <b>Subject:</b>{" "}
          <span data-testid="k72-broadcast-subject">
            {truncate(subject, 140) || "(none)"}
          </span>
        </div>
        <div style={{ whiteSpace: "pre-wrap" }}>
          <b>Body preview:</b>{" "}
          <span data-testid="k72-broadcast-body">
            {truncate(bodyPreview, 240) || "(none)"}
          </span>
        </div>
      </div>
      {requiresTypeConfirm ? (
        <div className="my-2">
          <label
            className="text-[11px] font-semibold block mb-1"
            style={{ color: colors.muted }}
            htmlFor="k72-typed-confirm-input"
          >
            Type <b>{tenantName}</b> to confirm this broadcast:
          </label>
          <input
            id="k72-typed-confirm-input"
            data-testid="k72-typed-confirm-input"
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="w-full px-2 py-1 rounded text-sm"
            style={{ background: colors.surface,
                      border: `1px solid ${
                        typedOk ? "#16A34A" : "#DC2626"}` }}
            autoComplete="off"
            spellCheck={false}
          />
          {!typedOk ? (
            <div className="text-[11px] mt-1"
                  style={{ color: "#B91C1C" }}
                  data-testid="k72-typed-confirm-hint">
              Type the tenant name exactly. Case-sensitive.
            </div>
          ) : null}
        </div>
      ) : null}
      <AlertDialogFooter>
        <AlertDialogCancel
          onClick={onCancel}
          data-testid="mass-messaging-confirm-cancel"
        >
          Cancel
        </AlertDialogCancel>
        <AlertDialogAction
          onClick={onConfirm}
          disabled={!typedOk || sending}
          style={{
            background: (!typedOk || sending) ? "#9CA3AF" : "#DC2626",
            color: "#fff",
            cursor: (!typedOk || sending) ? "not-allowed" : "pointer",
          }}
          data-testid="mass-messaging-confirm-send"
        >
          {sending
            ? "Sending…"
            : isBroadcast
              ? "Yes, send broadcast"
              : "Yes, send now"}
        </AlertDialogAction>
      </AlertDialogFooter>
    </>
  );
}


function PillMultiSelect({ label, options, selectedIds, onChange, testid }) {
  const selectedSet = new Set(selectedIds);
  const toggle = (id) => {
    const s = new Set(selectedSet);
    if (s.has(id)) s.delete(id); else s.add(id);
    onChange(Array.from(s));
  };
  return (
    <div data-testid={testid}>
      <label
        className="text-[10px] font-bold uppercase block mb-1"
        style={{ color: colors.muted }}
      >
        {label}
      </label>
      <div className="flex flex-wrap gap-1">
        {options.length === 0 ? (
          <span className="text-[11px] italic"
                 style={{ color: colors.muted }}>
            No options
          </span>
        ) : options.map((opt) => {
          const on = selectedSet.has(opt.id);
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => toggle(opt.id)}
              className="text-[11px] px-2 py-0.5 rounded-full font-semibold transition-colors"
              style={{
                background: on ? (opt.color || colors.brand) : colors.surfaceSecondary,
                color: on ? "#111827" : colors.onSurface,
                border: `1px solid ${on ? "transparent" : colors.border}`,
                cursor: "pointer",
              }}
              data-testid={`${testid}-opt-${opt.id}`}
              aria-pressed={on}
            >
              {opt.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

