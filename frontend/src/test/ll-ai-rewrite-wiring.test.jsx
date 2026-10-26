/**
 * Ticket LL · Feb-2026 — Commit 3 wiring smoke tests.
 *
 * Source-shape locks (not full mount) on every compose surface
 * wired with <AiRewriteButton>.  Verifies:
 *   * The ``@/components/ai/AiRewriteButton`` import is present.
 *   * The component renders inside the compose region.
 *   * KK's reserved placeholder (``mass-text-rewrite-placeholder``
 *     disabled chip) was REMOVED and the live component took its
 *     place inside the ``mass-text-rewrite-slot`` container.
 *
 * Deliberately avoids full component mount to keep this suite
 * fast + isolated from parent-tree transitive deps.  Each
 * surface's component unit tests already cover rendering behaviour.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


function readSrc(rel) {
  return fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");
}


const _IMPORT_RE = /import AiRewriteButton from "@\/components\/ai\/AiRewriteButton"/;
const _RENDER_RE = /<AiRewriteButton[\s\S]{0,500}?dataTestid="/;


describe("Ticket LL · Commit 3 wiring · MassTextModal (KK slot swap)", () => {
  const SRC = readSrc("src/components/customers/MassTextModal.jsx");

  it("imports AiRewriteButton", () => {
    expect(SRC).toMatch(_IMPORT_RE);
  });

  it("renders <AiRewriteButton> inside the mass-text-rewrite-slot", () => {
    const slotIdx = SRC.indexOf('data-testid="mass-text-rewrite-slot"');
    expect(slotIdx).toBeGreaterThan(-1);
    const slotBlock = SRC.slice(slotIdx, slotIdx + 800);
    expect(slotBlock).toMatch(/<AiRewriteButton/);
    expect(slotBlock).toMatch(/dataTestid="mass-text-rewrite-btn"/);
  });

  it("removes KK's inert placeholder button (regression lock)", () => {
    expect(SRC).not.toMatch(/data-testid="mass-text-rewrite-placeholder"/);
    expect(SRC).not.toMatch(/AI rewrite \(coming soon · Ticket LL\)/);
  });
});


describe("Ticket LL · Commit 3 wiring · LeadComposeModal", () => {
  const SRC = readSrc("src/pages/leads/LeadComposeModal.jsx");

  it("imports AiRewriteButton", () => {
    expect(SRC).toMatch(_IMPORT_RE);
  });

  it("renders <AiRewriteButton> near the body textarea", () => {
    expect(SRC).toMatch(/<AiRewriteButton[\s\S]{0,400}?dataTestid="lead-compose-rewrite-btn"/);
    // Must sit ABOVE the body textarea so it reads as a header
    // toolbar for the compose field.
    const btnIdx = SRC.indexOf('dataTestid="lead-compose-rewrite-btn"');
    const textareaIdx = SRC.indexOf('data-testid="lead-compose-body"');
    expect(btnIdx).toBeGreaterThan(-1);
    expect(textareaIdx).toBeGreaterThan(-1);
    expect(btnIdx).toBeLessThan(textareaIdx);
  });
});


describe("Ticket LL · Commit 3 wiring · MassMessagingComposeDialog", () => {
  const SRC = readSrc("src/components/mass-messaging/MassMessagingComposeDialog.jsx");

  it("imports AiRewriteButton", () => {
    expect(SRC).toMatch(_IMPORT_RE);
  });

  it("renders <AiRewriteButton> above the body Textarea", () => {
    expect(SRC).toMatch(/<AiRewriteButton[\s\S]{0,400}?dataTestid="mass-messaging-rewrite-btn"/);
    const btnIdx = SRC.indexOf('dataTestid="mass-messaging-rewrite-btn"');
    const textareaIdx = SRC.indexOf('data-testid="mass-messaging-body-input"');
    expect(btnIdx).toBeGreaterThan(-1);
    expect(textareaIdx).toBeGreaterThan(-1);
    expect(btnIdx).toBeLessThan(textareaIdx);
  });
});


describe("Ticket LL · Commit 3 wiring · TemplateEditor (SMS branch only)", () => {
  const SRC = readSrc("src/components/marketing/TemplateEditor.jsx");

  it("imports AiRewriteButton", () => {
    expect(SRC).toMatch(_IMPORT_RE);
  });

  it("renders <AiRewriteButton> in the SMS editor toolbar", () => {
    expect(SRC).toMatch(/<AiRewriteButton[\s\S]{0,400}?dataTestid="template-editor-sms-rewrite-btn"/);
    // Lives INSIDE the SMS editor region (above the sms-textarea),
    // NOT inside the email editor region.  Pin the position so a
    // refactor can't quietly move it into the TipTap toolbar
    // (which would silently plain-text-strip the HTML body).
    const btnIdx = SRC.indexOf('dataTestid="template-editor-sms-rewrite-btn"');
    const smsRegionIdx = SRC.indexOf('data-testid="template-editor-sms"');
    const smsTextareaIdx = SRC.indexOf('data-testid="sms-textarea"');
    expect(smsRegionIdx).toBeGreaterThan(-1);
    expect(btnIdx).toBeGreaterThan(smsRegionIdx);
    expect(btnIdx).toBeLessThan(smsTextareaIdx);
  });
});


describe("Ticket LL · Commit 3 wiring · CustomerDetail Send dialog (Q2 unlock)", () => {
  const SRC = readSrc("src/pages/customers/CustomerDetail.jsx");

  it("imports AiRewriteButton", () => {
    expect(SRC).toMatch(_IMPORT_RE);
  });

  it("renders <AiRewriteButton> next to the MESSAGE label", () => {
    expect(SRC).toMatch(/<AiRewriteButton[\s\S]{0,500}?dataTestid="cd-send-rewrite-btn"/);
    // The rewrite button MUST live inside the Send dialog's
    // MESSAGE flex row, NOT in the dropdown toolbar or elsewhere.
    const btnIdx = SRC.indexOf('dataTestid="cd-send-rewrite-btn"');
    const msgLabelIdx = SRC.lastIndexOf("<span>MESSAGE</span>", btnIdx);
    const msgTextareaIdx = SRC.indexOf('data-testid="cd-send-message"', btnIdx);
    expect(msgLabelIdx).toBeGreaterThan(-1);
    expect(msgTextareaIdx).toBeGreaterThan(-1);
    expect(btnIdx).toBeGreaterThan(msgLabelIdx);
    expect(btnIdx).toBeLessThan(msgTextareaIdx);
  });

  it("coexists with the existing cd-ai-draft-btn (Draft + Rewrite distinct UX)", () => {
    // Draft generates a reply from recipient context; Rewrite
    // polishes an operator-authored draft.  Both ship.
    expect(SRC).toMatch(/data-testid="cd-ai-draft-btn"/);
    expect(SRC).toMatch(/dataTestid="cd-send-rewrite-btn"/);
  });

  it("Q2 unlock diff footprint — rewrite wiring lives in a bounded range", () => {
    // The ``cd-send-rewrite-btn`` sits in the Send dialog's
    // compose block (between cd-send-subject + cd-send-message
    // testids).  This pin ensures a future diff cannot move the
    // wiring outside the compose region.
    const btnIdx = SRC.indexOf('dataTestid="cd-send-rewrite-btn"');
    const prevRegionIdx = SRC.indexOf('testid="cd-send-subject"');
    const nextRegionIdx = SRC.indexOf('data-testid="cd-send-attachments-row"');
    expect(btnIdx).toBeGreaterThan(prevRegionIdx);
    expect(btnIdx).toBeLessThan(nextRegionIdx);
  });
});
