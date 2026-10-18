/**
 * TD-67 / TD-76 Phase A — mobile portal photo rendering parity.
 *   - resolvePortalMediaUri: data: passthrough · relative → backend origin ·
 *     `?auth=` ONLY on /api/customers/me/ + /api/files/ (idempotent, fragment-safe)
 *   - canonical field chains (thumb_url / full_url, legacy url fallback)
 *   - groupPhotosByDateAndVisit: web tiebreak contract
 *   - Photos screen + SR detail render the resolved URIs (incl. new Job Photos grid)
 */
import React from "react";
import { render, waitFor, fireEvent } from "@testing-library/react-native";
import { Image as ExpoImage } from "expo-image";

import {
  withAuthToken, resolvePortalMediaUri, portalPhotoThumbRaw, portalPhotoFullRaw,
  portalJobPhotoRaw, groupPhotosByDateAndVisit,
} from "@/src/lib/portalMediaUri";
import { api } from "@/src/api";
import PortalPhotos from "@/app/portal/photos";
import PortalServiceReportDetail from "@/app/portal/service-report/[id]";

process.env.EXPO_PUBLIC_BACKEND_URL = "https://be.test";
const BASE = "https://be.test";

jest.mock("@/src/api", () => ({
  api: { get: jest.fn() },
  api_base: () => `${process.env.EXPO_PUBLIC_BACKEND_URL}/api`,
  getAuthToken: jest.fn(async () => "tok123"),
}));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useFocusEffect: (cb: any) => React.useEffect(cb, [cb]),
    useLocalSearchParams: () => ({ id: "sr1" }),
    useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  };
});
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/components/interactive", () => ({ ClickableAddress: () => null }));

describe("withAuthToken / resolvePortalMediaUri", () => {
  it("stamps ?auth= and & when a query exists; replaces (idempotent); keeps #fragment", () => {
    expect(withAuthToken("https://x/a", "t")).toBe("https://x/a?auth=t");
    expect(withAuthToken("https://x/a?w=1", "t")).toBe("https://x/a?w=1&auth=t");
    expect(withAuthToken("https://x/a?auth=old&w=1", "new")).toBe("https://x/a?auth=new&w=1");
    expect(withAuthToken("https://x/a#f", "t")).toBe("https://x/a?auth=t#f");
    expect(withAuthToken("https://x/a", "")).toBe("https://x/a");
  });
  it("relative public path → backend origin, NO token", () => {
    expect(resolvePortalMediaUri("/api/public/job-photo/j/p", "tok")).toBe(`${BASE}/api/public/job-photo/j/p`);
  });
  it("authed customer route → ?auth= (relative or absolute)", () => {
    expect(resolvePortalMediaUri("/api/customers/me/jobs/j/photos/p", "tok")).toBe(
      `${BASE}/api/customers/me/jobs/j/photos/p?auth=tok`,
    );
    expect(resolvePortalMediaUri("https://app.example.com/api/customers/me/jobs/j/photos/p", "tok")).toBe(
      "https://app.example.com/api/customers/me/jobs/j/photos/p?auth=tok",
    );
    expect(resolvePortalMediaUri("/api/files/f1/download", "tok")).toBe(`${BASE}/api/files/f1/download?auth=tok`);
  });
  it("data: URIs untouched; empty → ''", () => {
    expect(resolvePortalMediaUri("data:image/png;base64,AAA", "tok")).toBe("data:image/png;base64,AAA");
    expect(resolvePortalMediaUri("", "tok")).toBe("");
    expect(resolvePortalMediaUri(null, "tok")).toBe("");
  });
});

describe("canonical field chains (legacy url fallback)", () => {
  it("thumb: thumb_url > thumb > url", () => {
    expect(portalPhotoThumbRaw({ thumb_url: "T", thumb: "t", url: "u" })).toBe("T");
    expect(portalPhotoThumbRaw({ thumb: "t", url: "u" })).toBe("t");
    expect(portalPhotoThumbRaw({ url: "u" })).toBe("u");
  });
  it("full: full_url > url > thumb_url > thumb", () => {
    expect(portalPhotoFullRaw({ full_url: "F", url: "u", thumb_url: "T" })).toBe("F");
    expect(portalPhotoFullRaw({ url: "u", thumb_url: "T" })).toBe("u");
    expect(portalPhotoFullRaw({ thumb_url: "T" })).toBe("T");
  });
  it("job photo: thumb_url > thumb > full_url > url", () => {
    expect(portalJobPhotoRaw({ full_url: "F", url: "u" })).toBe("F");
    expect(portalJobPhotoRaw({ thumb_url: "T", full_url: "F" })).toBe("T");
  });
});

describe("groupPhotosByDateAndVisit (web TD-76de contract)", () => {
  const rows = [
    { id: "a", job_id: "jB", job_title: "Pool B", submitted_at: "2026-08-27T15:00:00Z" },
    { id: "b", job_id: "jA", job_title: "Pool A", submitted_at: "2026-08-27T09:00:00Z" },
    { id: "c", job_id: "jC", job_title: "Lawn", submitted_at: "2026-08-28T10:00:00Z" },
    { id: "d", job_id: "jZ", job_title: "Same time Z", submitted_at: "2026-08-26T10:00:00Z" },
    { id: "e", job_id: "jY", job_title: "Same time Y", submitted_at: "2026-08-26T10:00:00Z" },
    { id: "f", job_id: "jB", job_title: "Pool B", submitted_at: "2026-08-27T15:05:00Z" },
  ];
  const g = groupPhotosByDateAndVisit(rows);
  it("dates DESC", () => expect(g.map((d) => d.day)).toEqual(["2026-08-28", "2026-08-27", "2026-08-26"]));
  it("visits submitted_at ASC within a day; photos keep BE order", () => {
    expect(g[1].visits.map((v) => v.visitKey)).toEqual(["jA", "jB"]);
    expect(g[1].visits[1].photos.map((p) => p.id)).toEqual(["a", "f"]);
  });
  it("job_id lex ASC tiebreak", () => expect(g[2].visits.map((v) => v.visitKey)).toEqual(["jY", "jZ"]));
  it("no stamp → 'Unknown date' (not dropped)", () => {
    expect(groupPhotosByDateAndVisit([{ id: "x", job_id: "j" }])[0].day).toBe("Unknown date");
  });
});

describe("screens render resolved URIs", () => {
  beforeEach(() => (api.get as jest.Mock).mockReset());

  it("Photos: thumb tile uses thumb_url absolutized; zoom uses full_url; empty-URL rows skipped; visit sub-header", async () => {
    (api.get as jest.Mock).mockResolvedValue({
      photos: [
        { id: "p1", job_id: "j1", job_title: "Weekly Pool", submitted_at: "2026-08-27T19:35:00Z",
          thumb_url: "/api/public/job-photo/j1/p1?w=320", full_url: "/api/public/job-photo/j1/p1", url: "/legacy" },
        { id: "p2", job_id: "j2", job_title: "Blank", submitted_at: "2026-08-27T20:00:00Z",
          thumb_url: "", full_url: "", url: "", thumb: "" },
      ],
      total: 2,
    });
    const q = render(<PortalPhotos />);
    const tile = await waitFor(() => q.getByTestId("portal-photos-item-p1"));
    expect(q.queryByTestId("portal-photos-item-p2")).toBeNull();
    expect(q.getByTestId("portal-photos-visit-header-2026-08-27-j1").props.children).toBe("Weekly Pool");
    expect(q.getByTestId("portal-photos-date-divider-2026-08-27")).toBeTruthy();
    const img = tile.findByType(ExpoImage);
    expect(img.props.source.uri).toBe(`${BASE}/api/public/job-photo/j1/p1?w=320`);
    fireEvent.press(tile);
    expect(([] as any[]).concat(q.getByTestId("portal-photo-zoom-image").props.source)[0].uri).toBe(`${BASE}/api/public/job-photo/j1/p1`);
  });

  it("SR detail: renders Job Photos with ?auth= and absolutizes relative visit photos", async () => {
    (api.get as jest.Mock).mockResolvedValue({
      id: "sr1", template: "pool", submitted_at: "2026-08-27T19:35:00Z",
      job: { id: "j1", title: "Pool", service_type: "Pool Cleaning" },
      photos: [{ id: "v1", url: "/api/public/service/u1/photo/v1" }],
      job_photos: [{ id: "jp1", thumb_url: "https://app.example.com/api/customers/me/jobs/j1/photos/jp1",
        full_url: "https://app.example.com/api/customers/me/jobs/j1/photos/jp1", url: "x" }],
    });
    const q = render(<PortalServiceReportDetail />);
    await waitFor(() => expect(q.getByTestId("portal-service-report-job-photos")).toBeTruthy());
    await waitFor(() =>
      expect(q.getByTestId("portal-service-report-job-photo-0").props.source.uri).toBe(
        "https://app.example.com/api/customers/me/jobs/j1/photos/jp1?auth=tok123",
      ),
    );
    expect(q.getByTestId("portal-service-report-photo-0").props.source.uri).toBe(
      `${BASE}/api/public/service/u1/photo/v1`,
    );
  });
});
