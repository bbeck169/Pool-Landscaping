/**
 * Phase F2a · Feb 2026 — Job Before/After Photos · Vitest.
 *
 * Contract-level tests. The FileUpload and FileList components ship
 * their own coverage in ``file-upload-components.test.jsx``; here we
 * assert F2a's specific wiring:
 *   - Two buckets rendered (Before + After)
 *   - Each bucket passes the correct ``purpose``
 *   - ``accept`` is restricted to ``image/*,video/mp4``
 *   - ``canDeletePhoto`` gate matches the F0 backend contract
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { Toaster } from "sonner";

// Capture the props FileUpload / FileList receive so we can assert
// on ``purpose``, ``accept``, etc. without spinning up the full API.
const uploadSpies = [];
const listSpies = [];

vi.mock("@/components/files/FileUpload", () => ({
  FileUpload: (props) => {
    uploadSpies.push(props);
    return <div data-testid={`mock-upload-${props.purpose}`} data-accept={props.accept} data-multiple={String(props.multiple)} data-linked-type={props.linkedEntityType} data-linked-id={props.linkedEntityId} />;
  },
}));

vi.mock("@/components/files/FileList", () => ({
  FileList: (props) => {
    listSpies.push(props);
    return <div data-testid={`mock-list-${props.purpose}`} data-linked-type={props.linkedEntityType} data-linked-id={props.linkedEntityId} data-can-delete={String(props.canDelete)} />;
  },
}));

import { JobBeforeAfterPhotos, canDeletePhoto } from "@/components/jobs/JobBeforeAfterPhotos";

beforeEach(() => {
  uploadSpies.length = 0;
  listSpies.length = 0;
  cleanup();
});

// ═══════════════════════════════════════════════════════════════════
// Section renders when a jobId is present
// ═══════════════════════════════════════════════════════════════════
describe("JobBeforeAfterPhotos · section render", () => {
  it("renders the container + both Before and After buckets", () => {
    render(<JobBeforeAfterPhotos jobId="job-1" user={{ id: "u1", role: "admin" }} />);
    expect(screen.getByTestId("job-before-after-photos")).toBeTruthy();
    expect(screen.getByTestId("job-photos-before")).toBeTruthy();
    expect(screen.getByTestId("job-photos-after")).toBeTruthy();
    expect(screen.getByTestId("job-before-after-photos-hint")).toBeTruthy();
  });

  it("returns null when jobId is falsy (defensive guard)", () => {
    const { container } = render(<JobBeforeAfterPhotos jobId={null} user={{ role: "admin" }} />);
    expect(container.textContent).toBe("");
  });
});

// ═══════════════════════════════════════════════════════════════════
// FileUpload props: purpose + accept + linked entity
// ═══════════════════════════════════════════════════════════════════
describe("JobBeforeAfterPhotos · FileUpload wiring", () => {
  it("Before bucket passes purpose='job_before_photo'", () => {
    render(<JobBeforeAfterPhotos jobId="job-A" user={{ role: "admin" }} />);
    const el = screen.getByTestId("mock-upload-job_before_photo");
    expect(el).toBeTruthy();
    expect(el.getAttribute("data-linked-type")).toBe("job");
    expect(el.getAttribute("data-linked-id")).toBe("job-A");
  });

  it("After bucket passes purpose='job_after_photo'", () => {
    render(<JobBeforeAfterPhotos jobId="job-A" user={{ role: "admin" }} />);
    const el = screen.getByTestId("mock-upload-job_after_photo");
    expect(el).toBeTruthy();
    expect(el.getAttribute("data-linked-type")).toBe("job");
    expect(el.getAttribute("data-linked-id")).toBe("job-A");
  });

  it("accept restricts to image/* + video/mp4 on BOTH buckets", () => {
    render(<JobBeforeAfterPhotos jobId="job-A" user={{ role: "admin" }} />);
    for (const p of ["job_before_photo", "job_after_photo"]) {
      const el = screen.getByTestId(`mock-upload-${p}`);
      expect(el.getAttribute("data-accept")).toBe("image/*,video/mp4");
      expect(el.getAttribute("data-multiple")).toBe("true");
    }
  });
});

// ═══════════════════════════════════════════════════════════════════
// FileList props: purpose filter + canDelete gate
// ═══════════════════════════════════════════════════════════════════
describe("JobBeforeAfterPhotos · FileList wiring", () => {
  it("Before list is scoped to purpose='job_before_photo'", () => {
    render(<JobBeforeAfterPhotos jobId="job-A" user={{ role: "admin" }} />);
    const el = screen.getByTestId("mock-list-job_before_photo");
    expect(el.getAttribute("data-linked-type")).toBe("job");
    expect(el.getAttribute("data-linked-id")).toBe("job-A");
  });

  it("After list is scoped to purpose='job_after_photo'", () => {
    render(<JobBeforeAfterPhotos jobId="job-A" user={{ role: "admin" }} />);
    const el = screen.getByTestId("mock-list-job_after_photo");
    expect(el.getAttribute("data-linked-type")).toBe("job");
    expect(el.getAttribute("data-linked-id")).toBe("job-A");
  });

  it("admin sees canDelete=true on both lists", () => {
    render(<JobBeforeAfterPhotos jobId="job-A" user={{ role: "admin" }} />);
    for (const p of ["job_before_photo", "job_after_photo"]) {
      const el = screen.getByTestId(`mock-list-${p}`);
      expect(el.getAttribute("data-can-delete")).toBe("true");
    }
  });

  it("pool_tech also sees canDelete=true (backend still gates per file)", () => {
    render(<JobBeforeAfterPhotos jobId="job-A" user={{ role: "pool_tech" }} />);
    const el = screen.getByTestId("mock-list-job_before_photo");
    expect(el.getAttribute("data-can-delete")).toBe("true");
  });
});

// ═══════════════════════════════════════════════════════════════════
// canDeletePhoto predicate — mirrors the F0 backend gate
// ═══════════════════════════════════════════════════════════════════
describe("canDeletePhoto", () => {
  it("admin can delete any file", () => {
    expect(canDeletePhoto({
      user: { id: "u1", role: "admin" },
      file: { uploaded_by_user_id: "u2" },
    })).toBe(true);
  });

  it("super_admin can delete any file", () => {
    expect(canDeletePhoto({
      user: { id: "u1", role: "super_admin" },
      file: { uploaded_by_user_id: "u2" },
    })).toBe(true);
  });

  it("uploader can delete their own file", () => {
    expect(canDeletePhoto({
      user: { id: "u1", role: "pool_tech" },
      file: { uploaded_by_user_id: "u1" },
    })).toBe(true);
  });

  it("non-admin cannot delete someone else's file", () => {
    expect(canDeletePhoto({
      user: { id: "u1", role: "pool_tech" },
      file: { uploaded_by_user_id: "u2" },
    })).toBe(false);
  });

  it("returns false when user is missing", () => {
    expect(canDeletePhoto({ user: null, file: { uploaded_by_user_id: "u1" } }))
      .toBe(false);
  });

  it("non-admin without a file argument cannot delete", () => {
    expect(canDeletePhoto({ user: { id: "u1", role: "pool_tech" } })).toBe(false);
  });

  it("is case-insensitive on the role", () => {
    expect(canDeletePhoto({
      user: { id: "u1", role: "ADMIN" }, file: { uploaded_by_user_id: "u2" },
    })).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════════
// Responsive grid classes — desktop side-by-side, mobile stack
// ═══════════════════════════════════════════════════════════════════
describe("JobBeforeAfterPhotos · responsive layout", () => {
  it("uses Tailwind grid-cols-1 sm:grid-cols-2 so mobile stacks and desktop is side-by-side", () => {
    const { container } = render(<JobBeforeAfterPhotos jobId="j" user={{ role: "admin" }} />);
    const grid = container.querySelector(".grid");
    expect(grid).toBeTruthy();
    const cls = grid.getAttribute("class") || "";
    expect(cls).toMatch(/grid-cols-1/);
    expect(cls).toMatch(/sm:grid-cols-2/);
  });
});
