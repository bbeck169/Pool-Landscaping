/**
 * Phase F2b · Feb 2026 — Invoice/Estimate Attachments · Vitest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

// Capture the props passed down so we can assert on ``purpose``,
// ``linkedEntityType``, ``accept``, ``canDelete`` without spinning up
// the API layer.
const uploadSpies = [];
const listSpies = [];
vi.mock("@/components/files/FileUpload", () => ({
  FileUpload: (props) => {
    uploadSpies.push(props);
    return <div data-testid={`mock-upload-${props.purpose}`}
                 data-accept={props.accept}
                 data-multiple={String(props.multiple)}
                 data-linked-type={props.linkedEntityType}
                 data-linked-id={props.linkedEntityId} />;
  },
}));
vi.mock("@/components/files/FileList", () => ({
  FileList: (props) => {
    listSpies.push(props);
    return <div data-testid={`mock-list-${props.purpose}`}
                 data-linked-type={props.linkedEntityType}
                 data-linked-id={props.linkedEntityId}
                 data-can-delete={String(props.canDelete)} />;
  },
}));

import {
  InvoiceAttachments, canUploadInvoiceAttachment,
} from "@/components/quotes/InvoiceAttachments";

beforeEach(() => {
  uploadSpies.length = 0;
  listSpies.length = 0;
  cleanup();
});

// ═══════════════════════════════════════════════════════════════════
// Render + branches
// ═══════════════════════════════════════════════════════════════════
describe("InvoiceAttachments · render", () => {
  it("renders the card on isInvoice=true", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "admin" }} />);
    expect(screen.getByTestId("doc-attachments-card")).toBeTruthy();
    expect(screen.getByTestId("doc-attachments-hint").textContent).toMatch(/invoice/);
  });

  it("renders the card on isInvoice=false (estimate branch)", () => {
    render(<InvoiceAttachments docId="est-1" isInvoice={false} user={{ role: "admin" }} />);
    expect(screen.getByTestId("doc-attachments-card")).toBeTruthy();
    expect(screen.getByTestId("doc-attachments-hint").textContent).toMatch(/estimate/);
  });

  it("returns null when docId is falsy (defensive)", () => {
    const { container } = render(
      <InvoiceAttachments docId={null} isInvoice={true} user={{ role: "admin" }} />,
    );
    expect(container.textContent).toBe("");
  });
});

// ═══════════════════════════════════════════════════════════════════
// FileUpload wiring
// ═══════════════════════════════════════════════════════════════════
describe("InvoiceAttachments · FileUpload wiring", () => {
  it("admin sees upload; passes correct purpose + linked entity", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "admin" }} />);
    const el = screen.getByTestId("mock-upload-invoice_attachment");
    expect(el.getAttribute("data-linked-type")).toBe("invoice");
    expect(el.getAttribute("data-linked-id")).toBe("inv-1");
  });

  it("accept restricts to image/* + application/pdf (no video)", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "admin" }} />);
    const el = screen.getByTestId("mock-upload-invoice_attachment");
    const accept = el.getAttribute("data-accept");
    expect(accept).toContain("image/");
    expect(accept).toContain("application/pdf");
    expect(accept).not.toContain("video");
    expect(el.getAttribute("data-multiple")).toBe("true");
  });

  it("customer role: upload UI is HIDDEN", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "customer" }} />);
    expect(screen.queryByTestId("mock-upload-invoice_attachment")).toBeNull();
  });

  it("pool_tech role: upload UI is HIDDEN (view + no upload)", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "pool_tech" }} />);
    expect(screen.queryByTestId("mock-upload-invoice_attachment")).toBeNull();
  });

  it("manager role: upload UI is SHOWN", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "manager" }} />);
    expect(screen.getByTestId("mock-upload-invoice_attachment")).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════
// FileList wiring
// ═══════════════════════════════════════════════════════════════════
describe("InvoiceAttachments · FileList wiring", () => {
  it("scopes to purpose='invoice_attachment' + linked entity", () => {
    render(<InvoiceAttachments docId="inv-42" isInvoice={true} user={{ role: "admin" }} />);
    const el = screen.getByTestId("mock-list-invoice_attachment");
    expect(el.getAttribute("data-linked-type")).toBe("invoice");
    expect(el.getAttribute("data-linked-id")).toBe("inv-42");
  });

  it("admin sees canDelete=true", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "admin" }} />);
    expect(screen.getByTestId("mock-list-invoice_attachment").getAttribute("data-can-delete"))
      .toBe("true");
  });

  it("customer sees canDelete=false (read-only branch)", () => {
    render(<InvoiceAttachments docId="inv-1" isInvoice={true} user={{ role: "customer" }} />);
    expect(screen.getByTestId("mock-list-invoice_attachment").getAttribute("data-can-delete"))
      .toBe("false");
  });
});

// ═══════════════════════════════════════════════════════════════════
// canUploadInvoiceAttachment predicate
// ═══════════════════════════════════════════════════════════════════
describe("canUploadInvoiceAttachment", () => {
  it("admin / super_admin / manager → true", () => {
    expect(canUploadInvoiceAttachment({ role: "admin" })).toBe(true);
    expect(canUploadInvoiceAttachment({ role: "super_admin" })).toBe(true);
    expect(canUploadInvoiceAttachment({ role: "manager" })).toBe(true);
  });
  it("customer / pool_tech / unknown → false", () => {
    expect(canUploadInvoiceAttachment({ role: "customer" })).toBe(false);
    expect(canUploadInvoiceAttachment({ role: "pool_tech" })).toBe(false);
    expect(canUploadInvoiceAttachment({ role: "" })).toBe(false);
    expect(canUploadInvoiceAttachment(null)).toBe(false);
  });
  it("role match is case-insensitive", () => {
    expect(canUploadInvoiceAttachment({ role: "ADMIN" })).toBe(true);
    expect(canUploadInvoiceAttachment({ role: "Manager" })).toBe(true);
  });
});
