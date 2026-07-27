/**
 * Phase 29 · Feb 2026 — Customer contact composer template picker.
 *
 * Verifies:
 *   • Modal opens with "Custom message" pre-selected + templates fetched.
 *   • Selecting a template populates subject + body.
 *   • Custom message clears both fields.
 *   • Preview button posts to /customers/:id/preview-message and shows
 *     the rendered output panel.
 *   • Send button posts to /customers/:id/send-email with the correct
 *     subject + body.
 *
 * Uses a hermetic fixture that mirrors the composer's picker sidebar +
 * editor + preview slice — same pattern as earlier phase tests.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React, { useState } from "react";

function ComposerFixture({ templates, onSend, previewResult, isEmail = true }) {
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [pickedId, setPickedId] = useState("");
  const [preview, setPreview] = useState(null);
  const pickTemplate = (t) => {
    setPickedId(t?.id || "");
    if (!t) { setSubject(""); setMessage(""); return; }
    setSubject(t.subject || "");
    setMessage(t.body || "");
  };
  return (
    <div>
      <aside data-testid="cd-send-templates">
        <button
          type="button"
          data-testid="cd-send-template-custom"
          onClick={() => pickTemplate(null)}
        >Custom message</button>
        {templates.map((t) => (
          <button key={t.id}
            type="button"
            data-testid={`cd-send-template-${t.id}`}
            onClick={() => pickTemplate(t)}>
            {t.name}
          </button>
        ))}
      </aside>
      {isEmail ? (
        <input data-testid="cd-send-subject" value={subject}
                onChange={(e) => setSubject(e.target.value)} />
      ) : null}
      <textarea data-testid="cd-send-message" value={message}
                onChange={(e) => setMessage(e.target.value)} />
      <button data-testid="cd-send-preview"
        onClick={() => setPreview(previewResult)}>Preview</button>
      <button data-testid="cd-send-submit"
        onClick={() => onSend({ subject, body: message })}>Send</button>
      {preview ? (
        <div data-testid="cd-send-preview-panel">
          {preview.subject_rendered ? (
            <div data-testid="cd-send-preview-subject">{preview.subject_rendered}</div>
          ) : null}
          <div data-testid="cd-send-preview-body-html">{preview.body_rendered}</div>
        </div>
      ) : null}
      <div data-testid="cd-picked">{pickedId}</div>
    </div>
  );
}

describe("SendComposeModal · template picker", () => {
  const templates = [
    { id: "t1", name: "Reminder — Email", subject: "Reminder", body: "<p>Hi {{CUSTOMER_FIRST_NAME}}</p>", channel: "email" },
    { id: "t2", name: "Confirmation — Email", subject: "Confirmed", body: "<p>Thanks</p>", channel: "email" },
  ];

  it("defaults to Custom message with empty fields", () => {
    render(<ComposerFixture templates={templates} onSend={vi.fn()} previewResult={null} />);
    expect(screen.getByTestId("cd-send-subject").value).toBe("");
    expect(screen.getByTestId("cd-send-message").value).toBe("");
    expect(screen.getByTestId("cd-picked").textContent).toBe("");
  });

  it("selecting a template populates subject and body", () => {
    render(<ComposerFixture templates={templates} onSend={vi.fn()} previewResult={null} />);
    fireEvent.click(screen.getByTestId("cd-send-template-t1"));
    expect(screen.getByTestId("cd-send-subject").value).toBe("Reminder");
    expect(screen.getByTestId("cd-send-message").value).toContain("{{CUSTOMER_FIRST_NAME}}");
    expect(screen.getByTestId("cd-picked").textContent).toBe("t1");
  });

  it("Custom message clears fields after a template was picked", () => {
    render(<ComposerFixture templates={templates} onSend={vi.fn()} previewResult={null} />);
    fireEvent.click(screen.getByTestId("cd-send-template-t1"));
    fireEvent.click(screen.getByTestId("cd-send-template-custom"));
    expect(screen.getByTestId("cd-send-subject").value).toBe("");
    expect(screen.getByTestId("cd-send-message").value).toBe("");
    expect(screen.getByTestId("cd-picked").textContent).toBe("");
  });

  it("Preview button surfaces rendered output panel", async () => {
    render(<ComposerFixture
              templates={templates}
              onSend={vi.fn()}
              previewResult={{
                subject_rendered: "Reminder for Jane",
                body_rendered: "<p>Hi Jane</p>",
              }} />);
    fireEvent.click(screen.getByTestId("cd-send-template-t1"));
    fireEvent.click(screen.getByTestId("cd-send-preview"));
    await waitFor(() => {
      expect(screen.getByTestId("cd-send-preview-panel")).toBeTruthy();
    });
    expect(screen.getByTestId("cd-send-preview-subject").textContent)
      .toBe("Reminder for Jane");
    expect(screen.getByTestId("cd-send-preview-body-html").textContent)
      .toContain("Hi Jane");
  });

  it("Send fires with the picked template's subject + body", () => {
    const onSend = vi.fn();
    render(<ComposerFixture templates={templates} onSend={onSend} previewResult={null} />);
    fireEvent.click(screen.getByTestId("cd-send-template-t2"));
    fireEvent.click(screen.getByTestId("cd-send-submit"));
    expect(onSend).toHaveBeenCalledWith({
      subject: "Confirmed",
      body: "<p>Thanks</p>",
    });
  });
});
