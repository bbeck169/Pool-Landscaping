/**
 * Feb-2026 · Universal mobile-responsive redesign · shared
 * Terms & Conditions section — pre-built slot ahead of queue
 * item #5 (dedicated Terms field on quote / estimate).
 *
 * Renders NOTHING when ``terms`` is empty / null so the current
 * production docs (which don't yet have a doc-level
 * ``terms_and_conditions`` field) surface no visual regression.
 *
 * When queue item #5 populates the field, this component starts
 * rendering automatically.
 *
 * Testid: ``estimate-terms-section`` (also ``${prefix}-terms-section``).
 */
import React from "react";


export default function DocTermsSection({
  terms,
  brandColor,
  testidPrefix = "estimate",
}) {
  const body = typeof terms === "string" ? terms.trim() : "";
  if (!body) return null;
  const brand = brandColor || "#0F172A";
  const paragraphs = body.split(/\n\s*\n/);
  return (
    <section
      className="doc-terms-section"
      data-testid={`${testidPrefix}-terms-section`}
      style={{
        marginTop: 20,
        padding: "16px 20px",
        background: "#F9FAFB",
        border: "1px solid #E5E7EB",
        borderRadius: 12,
        fontSize: 13,
        lineHeight: 1.6,
        color: "#374151",
      }}
    >
      <h3
        data-testid={`${testidPrefix}-terms-heading`}
        style={{
          color: brand,
          fontSize: 15,
          fontWeight: 800,
          marginBottom: 10,
        }}
      >
        Terms &amp; Conditions
      </h3>
      <div data-testid={`${testidPrefix}-terms-body`}>
        {paragraphs.map((p, i) => (
          <p key={i} style={{ marginBottom: i < paragraphs.length - 1 ? 8 : 0 }}>
            {p}
          </p>
        ))}
      </div>
    </section>
  );
}
