/**
 * JobCard primary photo — slim `photo_thumb_urls[]` (customer profile /
 * jobs list) with backend prefix, legacy `photos[]` fallback, and the
 * "No primary photo" placeholder for genuinely-missing / failed images.
 */
process.env.EXPO_PUBLIC_BACKEND_URL = "https://api.test/";
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));
jest.mock("expo-image", () => {
  const { View } = require("react-native");
  return { Image: (p: any) => <View {...p} /> };
});

import React from "react";
import { render, fireEvent } from "@testing-library/react-native";
import { JobCard, _buildPhotoUri, jobPhotoUris } from "@/src/components/widgets";

const base = { id: "j1", title: "Weekly", status: "completed", scheduled_date: "2026-08-19" };
const img = (r: any) => r.queryByTestId("job-card-photo-img-j1");

describe("JobCard primary photo", () => {
  it("slim row: renders photo_thumb_urls[0] prefixed with EXPO_PUBLIC_BACKEND_URL", () => {
    const r = render(<JobCard job={{ ...base, photo_count: 2, photo_ids: ["p1", "p2"], photo_thumb_urls: ["/api/public/job-photo/j1/p1/thumb", "/api/public/job-photo/j1/p2/thumb"] }} />);
    expect(img(r).props.source).toEqual({ uri: "https://api.test/api/public/job-photo/j1/p1/thumb" });
    expect(r.queryByText("No primary photo")).toBeNull();
    expect(r.getByTestId("job-card-thumb-0-j1")).toBeTruthy(); // strip shows p2
  });

  it("legacy row: falls back to photos[0].url (absolute URL untouched)", () => {
    const r = render(<JobCard job={{ ...base, photos: [{ id: "p1", url: "https://cdn.test/a.jpg" }] }} />);
    expect(img(r).props.source).toEqual({ uri: "https://cdn.test/a.jpg" });
  });

  it("no photos → 'No primary photo'", () => {
    const r = render(<JobCard job={{ ...base, photo_count: 0, photo_ids: [], photo_thumb_urls: [] }} />);
    expect(img(r)).toBeNull();
    expect(r.getByText("No primary photo")).toBeTruthy();
  });

  it("first photo with null URL → 'No primary photo'", () => {
    const r = render(<JobCard job={{ ...base, photos: [{ id: "p1", url: null }] }} />);
    expect(img(r)).toBeNull();
    expect(r.getByText("No primary photo")).toBeTruthy();
  });

  it("image load failure (expired signed URL / network) → 'No primary photo'", () => {
    const r = render(<JobCard job={{ ...base, photo_thumb_urls: ["/api/public/job-photo/j1/p1/thumb"] }} />);
    fireEvent(img(r), "error");
    expect(img(r)).toBeNull();
    expect(r.getByText("No primary photo")).toBeTruthy();
  });
});

describe("URL helpers (mirror web JobPhotoThumbs `${BACKEND}${url}`)", () => {
  it("prefixes only relative paths", () => {
    expect(_buildPhotoUri("/api/x")).toBe("https://api.test/api/x");
    expect(_buildPhotoUri("api/x")).toBe("https://api.test/api/x");
    expect(_buildPhotoUri("https://s3/x")).toBe("https://s3/x");
    expect(_buildPhotoUri("data:image/png;base64,AA")).toBe("data:image/png;base64,AA");
    expect(_buildPhotoUri(undefined)).toBeUndefined();
  });

  it("prefers photo_thumb_urls over legacy photos", () => {
    expect(jobPhotoUris({ photo_thumb_urls: ["/t1"], photos: [{ url: "https://old" }] })).toEqual(["https://api.test/t1"]);
    expect(jobPhotoUris({ photos: [{ public_url: "https://p" }, { data: "data:x" }] })).toEqual(["https://p", "data:x"]);
  });
});
