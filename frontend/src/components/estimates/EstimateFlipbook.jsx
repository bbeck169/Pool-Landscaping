/**
 * Feb-2026 · Interactive Flipbook Estimate Viewer — customer-facing.
 *
 * Renders a proposal as a page-flip book (``react-pageflip``) when
 * the admin toggled ``flipbook_enabled`` on the estimate. Reuses the
 * classic ``<EstimateView>`` accept / decline / PDF handlers via
 * props so behaviour is identical — only the presentation changes.
 *
 * Page layout (dynamic based on data):
 *   1.  **Cover**    — logo, business name, proposal title/number,
 *                       prepared for {customer}, prepared date,
 *                       Download PDF button, flip hint.
 *   2.  **Filler**   — ONLY when service groups < 2 (empty or single
 *                       group estimates). "Our Process" + "Our
 *                       Guarantee" pulled from tenant settings when
 *                       set; static English fallback otherwise.
 *   3.  **Services** — one page per service group. Line items in
 *                       clean two-column layout. Group subtotal.
 *   4.  **Total**    — grand total, tax, discount, valid-until.
 *   5.  **Sign**     — Approve / Decline CTAs. Signature-gate hint
 *                       when the tenant requires it. Decline reason
 *                       is captured on the classic decline modal
 *                       (the parent EstimateView owns that modal).
 *
 * Each page uses ``flipbook_background_ids[i % len]`` as a subtle
 * background with a translucent overlay for legibility. Empty
 * background list → soft tenant-primary tint. Broken image URLs
 * fail silently to that tint.
 *
 * NB: react-pageflip's ``<HTMLFlipBook>`` is imported through
 * ``FlipbookShim`` so a future upstream / fork migration is a single-
 * file swap.
 */
import React, { useMemo, useRef, useState } from "react";
import { Download, ChevronRight, Loader2, Check, X } from "lucide-react";

import Flipbook from "@/components/estimates/FlipbookShim";


// ─── helpers ───────────────────────────────────────────────────────


function _fmtMoney(n, currency) {
  const c = String(currency || "USD").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: c,
    }).format(Number(n || 0));
  } catch {
    return `$${Number(n || 0).toFixed(2)}`;
  }
}

function _fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric",
  }); } catch { return String(iso).slice(0, 10); }
}

function _bgUrl(id) {
  return `/api/marketing/media/${encodeURIComponent(id)}/download`;
}


/** Feb-2026 · Interactive Flipbook Estimate Viewer — page background
 * URL resolver.
 *
 * Prefers the pre-signed URL emitted by the payload builder
 * (``flipbook_background_urls[i]``) because it carries the HMAC
 * signature needed for anonymous ``<img>`` tags to load
 * ``/api/marketing/media/{mid}/download`` without an
 * ``Authorization`` header. Falls back to the raw path when the
 * signed URL is missing (defensive — an older payload shape or an
 * admin preview that skipped signing). Falls back to ``null`` when
 * the tenant has no backgrounds attached (empty list → soft tint).
 */
function _resolveBgUrl(signedList, idList, i) {
  if (Array.isArray(signedList) && signedList.length > 0) {
    return signedList[i % signedList.length] || null;
  }
  if (Array.isArray(idList) && idList.length > 0) {
    const _id = idList[i % idList.length];
    return _id ? _bgUrl(_id) : null;
  }
  return null;
}


/** Group the payload's ``line_items`` by ``service_category_id``,
 * preserving first-appearance order (matches the backend's
 * ``group_lines_for_customer`` invariant). Uses labels from the
 * server-computed ``customer_view.groups`` when available.
 */
function _groupLines(lineItems, customerView) {
  const byKey = new Map();
  const labelByKey = new Map();
  for (const g of (customerView?.groups || [])) {
    labelByKey.set(String(g.group_key), {
      label: g.label || "Services",
      description: g.description || "",
    });
  }
  for (const li of (lineItems || [])) {
    const raw = li.service_category_id;
    const key = (raw && String(raw).trim()) || "__other__";
    if (!byKey.has(key)) {
      const meta = labelByKey.get(key) || {};
      byKey.set(key, {
        key,
        label: meta.label
                || (key === "__other__" ? "Additional Services" : "Services"),
        description: meta.description || "",
        lines: [],
        subtotal: 0,
      });
    }
    const bucket = byKey.get(key);
    const qty = Number(li.quantity || 0);
    const price = Number(li.unit_price || 0);
    const sub = qty * price;
    bucket.lines.push({
      id: li.id, description: li.description || "",
      qty, unit_price: price, subtotal: sub,
      declined: String(li.customer_status || "") === "declined",
    });
    bucket.subtotal += sub;
  }
  return Array.from(byKey.values());
}


// ─── page primitives ───────────────────────────────────────────────


/** Render prop pattern — every page shares the same background +
 * overlay + inner content padding contract. ``react-pageflip``
 * expects each child of ``<HTMLFlipBook>`` to be a plain DOM element
 * (not a fragment). We wrap in a single ``<div>`` with the required
 * dimensions locked from CSS variables.
 */
const FlipPage = React.forwardRef(function FlipPage(
  { bgSrc, bgLabel, tint, children, testid },
  ref,
) {
  return (
    <div
      ref={ref}
      data-testid={testid}
      className="flipbook-page"
      style={{
        // Base surface + subtle tenant tint so pages without a
        // background image still feel branded rather than white.
        backgroundColor: tint || "#f8fafc",
        position: "relative",
        overflow: "hidden",
        width: "100%", height: "100%",
        boxShadow: "inset 0 0 0 1px rgba(15,23,42,0.06)",
      }}
    >
      {bgSrc ? (
        <img
          src={bgSrc}
          alt=""
          onError={(e) => {
            // Broken image (deleted / cross-tenant / signed URL
            // expired). Log once + let the tint show through.
            if (!e.currentTarget.dataset.warned) {
              e.currentTarget.dataset.warned = "1";
              // eslint-disable-next-line no-console
              console.warn(
                `[flipbook] background image failed to load: ${bgLabel || bgSrc}`,
              );
            }
            e.currentTarget.style.visibility = "hidden";
          }}
          style={{
            position: "absolute", inset: 0,
            width: "100%", height: "100%",
            objectFit: "cover",
            zIndex: 0,
          }}
        />
      ) : null}
      {/* Legibility overlay — translucent white on top of the image
          so body copy stays readable across any photo. Applied
          conditionally so tint-only pages don't get double-washed. */}
      {bgSrc ? (
        <div
          style={{
            position: "absolute", inset: 0,
            backgroundColor: "rgba(255,255,255,0.85)",
            zIndex: 1,
          }}
        />
      ) : null}
      <div
        className="flipbook-inner"
        style={{
          position: "relative", zIndex: 2,
          padding: "48px 48px",
          height: "100%",
          display: "flex", flexDirection: "column",
          fontFamily:
            'Georgia, "Times New Roman", serif',
          color: "#0f172a",
        }}
      >
        {children}
      </div>
    </div>
  );
});


// ─── main component ────────────────────────────────────────────────


export function EstimateFlipbook({
  data, onAccept, onDeclineClick, onDownloadPdf,
  signatureGateBlocked, onSignNow, actionable,
  busy, toast,
}) {
  const flipbookRef = useRef(null);
  const [pageIdx, setPageIdx] = useState(0);

  const backgrounds = useMemo(
    () => (Array.isArray(data?.flipbook_background_ids)
            ? data.flipbook_background_ids : []),
    [data?.flipbook_background_ids],
  );
  const signedBackgrounds = useMemo(
    () => (Array.isArray(data?.flipbook_background_urls)
            ? data.flipbook_background_urls : []),
    [data?.flipbook_background_urls],
  );
  const bgForPage = (i) => _resolveBgUrl(signedBackgrounds, backgrounds, i);
  const bgLabelForPage = (i) => (backgrounds.length
    ? String(backgrounds[i % backgrounds.length] || "")
    : "");

  const groups = useMemo(
    () => _groupLines(data?.line_items || [], data?.customer_view),
    [data?.line_items, data?.customer_view],
  );

  // Filler pages surface ONLY on lean estimates so 3+ service groups
  // don't get padded with generic corporate-copy pages.
  const filler = useMemo(() => {
    if (groups.length >= 2) return [];
    // Tenant-brandable copy lives on ``settings.estimate_flipbook_copy``
    // (future admin editor). Fallback = clean English that reads
    // professionally.  Stored on ``data.company`` since the payload
    // already includes tenant-facing text there.
    const _copy = data?.company?.estimate_flipbook_copy || {};
    return [
      {
        key: "process",
        title: "Our Process",
        body: _copy.our_process
              || (
                "Every project starts with a conversation. From the "
                + "moment you approve this proposal we schedule a "
                + "pre-work walkthrough, confirm materials, and pick a "
                + "start date that respects your calendar. On the day, "
                + "our team arrives on time, protects your property, "
                + "and leaves the site cleaner than we found it. Each "
                + "milestone comes with a photo update so you always "
                + "know where the work stands."
              ),
      },
      {
        key: "guarantee",
        title: "Our Guarantee",
        body: _copy.our_guarantee
              || (
                "If any part of the work does not meet the standard "
                + "described in this proposal, we come back and make "
                + "it right — no surcharge, no scheduling hurdles. Our "
                + "materials carry manufacturer warranties, our "
                + "workmanship is covered for a full season, and every "
                + "invoice ships with the numbers you approved here. "
                + "Your satisfaction is the metric that runs our shop."
              ),
      },
    ];
  }, [groups.length, data?.company]);

  // Page indices — assemble in order so nav dots and background
  // cycling stay in sync.
  const pages = useMemo(() => {
    const arr = [];
    arr.push({ kind: "cover", key: "cover" });
    for (const f of filler) arr.push({ kind: "filler", key: `f-${f.key}`, filler: f });
    for (const g of groups) arr.push({ kind: "group", key: `g-${g.key}`, group: g });
    arr.push({ kind: "total", key: "total" });
    arr.push({ kind: "accept", key: "accept" });
    return arr;
  }, [filler, groups]);

  const totalPages = pages.length;

  // ── Interactions ────────────────────────────────────────────────

  const flipTo = (n) => {
    try { flipbookRef.current?.pageFlip()?.flip(n); } catch { /* ignore */ }
    setPageIdx(n);
  };
  const onFlip = (e) => { setPageIdx(Number(e?.data ?? 0)); };

  // Keyboard nav — arrow left/right flips one page.
  React.useEffect(() => {
    const onKey = (ev) => {
      if (ev.key === "ArrowRight") {
        try { flipbookRef.current?.pageFlip()?.flipNext(); } catch { /* ignore */ }
      } else if (ev.key === "ArrowLeft") {
        try { flipbookRef.current?.pageFlip()?.flipPrev(); } catch { /* ignore */ }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Print stylesheet — stack pages vertically, hide flipbook chrome,
  // let the browser paginate naturally. Scoped selector so we don't
  // touch surrounding admin surfaces.
  const _printCss = `
    @media print {
      .flipbook-print-stack .flipbook-page { page-break-after: always;
        height: auto !important; box-shadow: none !important; }
      .flipbook-print-stack .flipbook-nav { display: none !important; }
      .flipbook-print-stack .stf__parent { display: block !important; }
    }
  `;

  const _title = data?.title || "Proposal";
  const _tenantName = data?.company?.name || "Our Team";
  const _tint = "#eef2ff"; // soft indigo — brand-safe neutral.

  return (
    <div className="flipbook-print-stack"
          data-testid="estimate-flipbook">
      <style>{_printCss}</style>

      {toast ? (
        <div
          className="text-center text-xs mb-2"
          style={{ color: "#0f172a" }}
          data-testid="flipbook-toast"
        >{toast}</div>
      ) : null}

      <div
        style={{
          display: "flex", justifyContent: "center",
          padding: "24px 8px",
        }}
      >
        <Flipbook
          ref={flipbookRef}
          width={640}
          height={880}
          size="stretch"
          minWidth={320}
          maxWidth={720}
          minHeight={440}
          maxHeight={960}
          maxShadowOpacity={0.35}
          showCover={true}
          flippingTime={700}
          usePortrait={true}
          startZIndex={0}
          drawShadow={true}
          onFlip={onFlip}
          className="flipbook-instance"
          data-testid="flipbook-instance"
        >
          {pages.map((p, i) => {
            if (p.kind === "cover") {
              return (
                <FlipPage
                  key={p.key}
                  bgSrc={bgForPage(i)}
                  bgLabel={bgLabelForPage(i)}
                  tint={_tint}
                  testid="flipbook-page-cover"
                >
                  <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center" }}>
                    {data?.company?.logo_url ? (
                      <img
                        src={data.company.logo_url}
                        alt={_tenantName}
                        style={{ maxHeight: 80, marginBottom: 16 }}
                      />
                    ) : (
                      <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 16 }}>
                        {_tenantName}
                      </div>
                    )}
                    <div style={{ fontSize: 42, fontWeight: 700, letterSpacing: "-0.02em", marginBottom: 8 }}>
                      {_title}
                    </div>
                    <div style={{ fontSize: 16, color: "#475569", marginBottom: 4 }}>
                      Proposal {data?.header?.estimate_number ? `· ${data.header.estimate_number}` : ""}
                    </div>
                    <div style={{ fontSize: 15, color: "#334155", marginTop: 24 }}>
                      Prepared for
                      <div style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>
                        {data?.bill_to?.name || "Valued Customer"}
                      </div>
                    </div>
                    <div style={{ fontSize: 13, color: "#64748b", marginTop: 16 }}>
                      {_fmtDate(data?.header?.estimate_date)}
                    </div>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <button
                      type="button"
                      onClick={onDownloadPdf}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm"
                      style={{ backgroundColor: "#0f172a", color: "#fff", fontFamily: "Inter, system-ui, sans-serif" }}
                      data-testid="flipbook-cover-download-pdf"
                    >
                      <Download size={14} /> Download PDF
                    </button>
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#475569", fontFamily: "Inter, system-ui, sans-serif", fontSize: 12 }}>
                      flip <ChevronRight size={14} />
                    </div>
                  </div>
                </FlipPage>
              );
            }
            if (p.kind === "filler") {
              return (
                <FlipPage
                  key={p.key}
                  bgSrc={bgForPage(i)}
                  bgLabel={bgLabelForPage(i)}
                  tint={_tint}
                  testid={`flipbook-page-filler-${p.filler.key}`}
                >
                  <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
                    <div style={{ fontSize: 12, letterSpacing: "0.24em", color: "#64748b", textTransform: "uppercase", marginBottom: 8 }}>
                      Chapter
                    </div>
                    <div style={{ fontSize: 34, fontWeight: 700, marginBottom: 24, letterSpacing: "-0.01em" }}>
                      {p.filler.title}
                    </div>
                    <p style={{ fontSize: 16, lineHeight: 1.65, color: "#1e293b", fontFamily: "Georgia, serif" }}>
                      {p.filler.body}
                    </p>
                  </div>
                </FlipPage>
              );
            }
            if (p.kind === "group") {
              const g = p.group;
              return (
                <FlipPage
                  key={p.key}
                  bgSrc={bgForPage(i)}
                  bgLabel={bgLabelForPage(i)}
                  tint={_tint}
                  testid={`flipbook-page-group-${g.key}`}
                >
                  <div style={{ fontSize: 12, letterSpacing: "0.24em", color: "#64748b", textTransform: "uppercase", marginBottom: 8 }}>
                    Services
                  </div>
                  <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 6 }}>
                    {g.label}
                  </div>
                  {g.description ? (
                    <div style={{ fontSize: 14, color: "#475569", marginBottom: 20 }}>
                      {g.description}
                    </div>
                  ) : <div style={{ marginBottom: 20 }} />}
                  <ul style={{ flex: 1, listStyle: "none", padding: 0, margin: 0, overflowY: "auto" }}>
                    {g.lines.map((li) => (
                      <li
                        key={li.id}
                        data-testid={`flipbook-line-${li.id}`}
                        style={{ display: "flex", justifyContent: "space-between", gap: 24, padding: "10px 0", borderBottom: "1px dashed rgba(15,23,42,0.15)", opacity: li.declined ? 0.55 : 1 }}
                      >
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 15, color: "#0f172a", textDecoration: li.declined ? "line-through" : "none" }}>
                            {li.description}
                          </div>
                          <div style={{ fontSize: 12, color: "#64748b", fontFamily: "Inter, system-ui, sans-serif", marginTop: 2 }}>
                            {li.qty} × {_fmtMoney(li.unit_price, data?.customer_view?.currency)}
                          </div>
                        </div>
                        <div style={{ fontSize: 15, fontWeight: 600, whiteSpace: "nowrap", fontFamily: "Inter, system-ui, sans-serif" }}>
                          {_fmtMoney(li.subtotal, data?.customer_view?.currency)}
                        </div>
                      </li>
                    ))}
                  </ul>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 16, borderTop: "1px solid rgba(15,23,42,0.15)", marginTop: 12 }}>
                    <div style={{ fontSize: 13, color: "#475569", fontFamily: "Inter, system-ui, sans-serif" }}>Group subtotal</div>
                    <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "Inter, system-ui, sans-serif" }}>
                      {_fmtMoney(g.subtotal, data?.customer_view?.currency)}
                    </div>
                  </div>
                </FlipPage>
              );
            }
            if (p.kind === "total") {
              const t = data?.totals || data?.customer_view || {};
              return (
                <FlipPage
                  key={p.key}
                  bgSrc={bgForPage(i)}
                  bgLabel={bgLabelForPage(i)}
                  tint={_tint}
                  testid="flipbook-page-total"
                >
                  <div style={{ fontSize: 12, letterSpacing: "0.24em", color: "#64748b", textTransform: "uppercase", marginBottom: 8 }}>
                    Investment
                  </div>
                  <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 24 }}>
                    Total
                  </div>
                  <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", fontFamily: "Inter, system-ui, sans-serif" }}>
                    <Row label="Subtotal" value={_fmtMoney(t.subtotal, t.currency)} />
                    {Number(t.discount) > 0 ? (
                      <Row label="Discount" value={`− ${_fmtMoney(t.discount, t.currency)}`} testid="flipbook-total-discount" />
                    ) : null}
                    <Row label="Tax" value={_fmtMoney(t.tax, t.currency)} />
                    <div style={{ height: 12 }} />
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "16px 0", borderTop: "2px solid #0f172a" }}>
                      <div style={{ fontSize: 18, fontWeight: 600 }}>Grand total</div>
                      <div style={{ fontSize: 32, fontWeight: 700 }} data-testid="flipbook-total-grand">
                        {_fmtMoney(t.total, t.currency)}
                      </div>
                    </div>
                  </div>
                  {data?.expires_at ? (
                    <div style={{ fontSize: 12, color: "#64748b", fontFamily: "Inter, system-ui, sans-serif" }}>
                      This proposal is valid until {_fmtDate(data.expires_at)}.
                    </div>
                  ) : null}
                </FlipPage>
              );
            }
            // Accept page
            return (
              <FlipPage
                key={p.key}
                bgSrc={bgForPage(i)}
                bgLabel={bgLabelForPage(i)}
                tint={_tint}
                testid="flipbook-page-accept"
              >
                <div style={{ fontSize: 12, letterSpacing: "0.24em", color: "#64748b", textTransform: "uppercase", marginBottom: 8 }}>
                  Ready
                </div>
                <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 16 }}>
                  Approve this proposal
                </div>
                <p style={{ fontSize: 15, lineHeight: 1.65, color: "#1e293b", marginBottom: 32, fontFamily: "Georgia, serif" }}>
                  When you approve we schedule your project and lock
                  in the pricing shown here. If anything needs
                  adjusting, decline with a short note and we'll be
                  in touch — no hard feelings.
                </p>
                {signatureGateBlocked ? (
                  <div
                    className="mb-3"
                    style={{ fontSize: 13, color: "#7c2d12", background: "#fff7ed", border: "1px solid #fed7aa", padding: 12, borderRadius: 8, fontFamily: "Inter, system-ui, sans-serif" }}
                    data-testid="flipbook-signature-hint"
                  >
                    Signature required before you can approve.{" "}
                    <button
                      type="button"
                      onClick={onSignNow}
                      className="underline"
                      data-testid="flipbook-sign-now"
                    >
                      Sign now
                    </button>
                  </div>
                ) : null}
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontFamily: "Inter, system-ui, sans-serif" }}>
                  <button
                    type="button"
                    onClick={onAccept}
                    disabled={!actionable || signatureGateBlocked || busy}
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-full text-white font-semibold disabled:opacity-50"
                    style={{ backgroundColor: "#16a34a" }}
                    data-testid="flipbook-accept-btn"
                  >
                    {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                    Approve
                  </button>
                  <button
                    type="button"
                    onClick={onDeclineClick}
                    disabled={!actionable || busy}
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-full font-semibold disabled:opacity-50"
                    style={{ border: "2px solid #0f172a", color: "#0f172a", backgroundColor: "transparent" }}
                    data-testid="flipbook-decline-btn"
                  >
                    <X size={16} /> Decline
                  </button>
                </div>
                {data?.decision ? (
                  <div
                    className="mt-6"
                    style={{ fontSize: 13, color: "#0f172a", fontFamily: "Inter, system-ui, sans-serif" }}
                    data-testid={`flipbook-decision-${data.decision}`}
                  >
                    Decision recorded: <strong>{data.decision}</strong>
                    {data.accepted_at ? ` on ${_fmtDate(data.accepted_at)}` : ""}
                    {data.declined_at ? ` on ${_fmtDate(data.declined_at)}` : ""}.
                  </div>
                ) : null}
              </FlipPage>
            );
          })}
        </Flipbook>
      </div>

      {/* Navigation dots — click to jump. */}
      <div
        className="flipbook-nav"
        style={{ display: "flex", justifyContent: "center", gap: 6, paddingBottom: 24 }}
      >
        {pages.map((_, i) => (
          <button
            key={i}
            type="button"
            onClick={() => flipTo(i)}
            aria-label={`Go to page ${i + 1} of ${totalPages}`}
            data-testid={`flipbook-nav-dot-${i}`}
            aria-current={i === pageIdx ? "page" : undefined}
            style={{
              width: i === pageIdx ? 24 : 8,
              height: 8,
              borderRadius: 4,
              border: 0,
              cursor: "pointer",
              backgroundColor: i === pageIdx ? "#0f172a" : "#cbd5e1",
              transition: "width 200ms ease",
            }}
          />
        ))}
      </div>
    </div>
  );
}


function Row({ label, value, testid }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: 15 }}
         data-testid={testid}>
      <div style={{ color: "#475569" }}>{label}</div>
      <div style={{ fontWeight: 500 }}>{value}</div>
    </div>
  );
}


export default EstimateFlipbook;
