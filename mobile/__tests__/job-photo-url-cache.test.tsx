/**
 * Fix 2 — Job photo URL cache test.
 *
 * Asserts that:
 *   1. `jobPhotoUrl` builds the correct public URL.
 *   2. `resolvePhotoSource` prefers URL over base64.
 *   3. `stripBase64FromReport` removes base64 blobs.
 *   4. Rendering a photo component uses URL, not base64.
 */
import React from "react";
import { render } from "@testing-library/react-native";
import { View, Text } from "react-native";

/* ── Mocks ───────────────────────────────────────────────────────── */

// Mock expo-image
jest.mock("expo-image", () => {
  const { View: V } = require("react-native");
  return {
    Image: (props: any) => <V testID={props.testID} source={props.source} />,
  };
});

// Set env for URL building BEFORE importing the module
const BACKEND_URL = "https://poolscape-audit.preview.emergentagent.com";
process.env.EXPO_PUBLIC_BACKEND_URL = BACKEND_URL;

// Now import — module reads env at load time
import {
  jobPhotoUrl,
  resolvePhotoSource,
  stripBase64FromReport,
  prefetchReportPhotos,
} from "../src/services/photoUrlCache";

// After import, read the actual BASE_URL the module captured
const EFFECTIVE_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";

/* ── Mirror component: renders a photo using resolvePhotoSource ───── */
function JobPhotoRenderer({ jobId, photo }: { jobId: string; photo: any }) {
  const { Image } = require("expo-image");
  const src = resolvePhotoSource(jobId, photo);
  if (!src) return <Text testID="no-photo">No photo</Text>;
  return (
    <View testID="photo-container">
      <Image
        source={{ uri: src }}
        testID="photo-image"
      />
      <Text testID="photo-source-type">
        {src.startsWith("data:") ? "base64" : "url"}
      </Text>
    </View>
  );
}

/* ── Tests ──────────────────────────────────────────────────────── */
describe("Fix 2 — Job photo URL cache", () => {
  it("1. jobPhotoUrl builds correct public URL", () => {
    const url = jobPhotoUrl("job-abc", "photo-123");
    expect(url).toContain("/api/public/job-photo/job-abc/photo-123");
  });

  it("2. resolvePhotoSource prefers URL over base64", () => {
    // Photo with explicit URL
    expect(resolvePhotoSource("j1", { id: "p1", url: "https://cdn.example.com/p1.jpg" }))
      .toBe("https://cdn.example.com/p1.jpg");

    // Photo with id only → builds public URL
    const resolved = resolvePhotoSource("j1", { id: "p1" });
    expect(resolved).toContain("/api/public/job-photo/j1/p1");
    expect(resolved).not.toContain("base64");

    // Legacy photo with base64 → fallback
    expect(resolvePhotoSource("j1", { base64: "abc123" }))
      .toBe("data:image/jpeg;base64,abc123");

    // Null photo
    expect(resolvePhotoSource("j1", null)).toBeNull();
  });

  it("3. stripBase64FromReport removes base64 blobs", () => {
    const report = {
      id: "sr-1",
      notes: "test",
      photos: [
        { id: "p1", base64: "AAAA=", some_field: "keep" },
        { id: "p2", data: "data:image/png;base64,BBB=", another: true },
        { id: "p3" }, // no base64 — unchanged
      ],
    };

    const cleaned = stripBase64FromReport(report);

    // Original is not mutated
    expect(report.photos[0].base64).toBe("AAAA=");

    // Cleaned version has no base64
    expect(cleaned.photos[0].base64).toBeUndefined();
    expect(cleaned.photos[0].some_field).toBe("keep");
    expect(cleaned.photos[0].id).toBe("p1");

    expect(cleaned.photos[1].data).toBeUndefined();
    expect(cleaned.photos[1].another).toBe(true);

    expect(cleaned.photos[2].id).toBe("p3");

    // Other fields preserved
    expect(cleaned.notes).toBe("test");
  });

  it("4. photo component renders URL source, not base64", () => {
    const photo = { id: "photo-xyz" };
    const { getByTestId } = render(
      <JobPhotoRenderer jobId="job-abc" photo={photo} />,
    );

    expect(getByTestId("photo-container")).toBeTruthy();
    const sourceType = getByTestId("photo-source-type");
    expect(sourceType.children[0]).toBe("url");
  });

  it("5. null report passes through stripBase64FromReport safely", () => {
    expect(stripBase64FromReport(null)).toBeNull();
    expect(stripBase64FromReport(undefined)).toBeUndefined();
    expect(stripBase64FromReport({})).toEqual({});
    expect(stripBase64FromReport({ photos: [] })).toEqual({ photos: [] });
  });
});
