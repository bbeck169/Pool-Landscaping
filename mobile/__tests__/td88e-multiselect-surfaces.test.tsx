/**
 * TD-88e · library multi-select per surface — each handler loops over
 * every picked asset through its existing pipeline, and passes its own
 * dynamic `remainingCap` as `selectionLimit`. Camera stays single-shot.
 *
 * Rendered: PhotoUploader (landscaping/pool checklist Internal Photos),
 * ServiceReportMediaUploader (Visit Media photos), Check-in composer.
 * Source-level: job detail (`app/job/[id].tsx` is too heavy to mount).
 */
import React from "react";
import * as fs from "fs";
import * as path from "path";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockLaunchLib = jest.fn();
const mockLaunchCam = jest.fn();
jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: jest.fn(async () => ({ granted: true, canAskAgain: true })),
  requestCameraPermissionsAsync: jest.fn(async () => ({ granted: true, canAskAgain: true })),
  launchImageLibraryAsync: (...a: any[]) => mockLaunchLib(...a),
  launchCameraAsync: (...a: any[]) => mockLaunchCam(...a),
}));
jest.mock("expo-image", () => {
  const { View } = jest.requireActual("react-native");
  return { Image: (p: any) => <View testID={p.testID} /> };
});
jest.mock("expo-video-thumbnails", () => ({ getThumbnailAsync: jest.fn(async () => ({ uri: "" })) }));
jest.mock("@/src/components/media/VideoPlayerModal", () => () => null);

const mockCapture = jest.fn(async (..._a: any[]) => {});
const mockPending = jest.fn(async (..._a: any[]): Promise<any[]> => []);
jest.mock("@/src/services/sync/photoWorker", () => ({
  capturePhoto: (...a: any[]) => mockCapture(...a),
  getPhotosForEntity: (...a: any[]) => mockPending(...a),
}));
jest.mock("@/src/offline", () => ({ useOnline: () => true }));
jest.mock("@/src/api", () => ({
  api: { get: jest.fn(async () => ({})), post: jest.fn(async () => ({})), del: jest.fn(async () => ({ photos: [] })) },
  api_base: () => "http://x/api", getAuthToken: jest.fn(async () => "t"),
  ApiError: class ApiError extends Error {},
}));

const mockSrUpload = jest.fn();
jest.mock("@/src/api/serviceReportMedia", () => {
  class OfflineError extends Error {}
  return {
    uploadServiceReportMedia: (...a: any[]) => mockSrUpload(...a),
    reorderServiceReportMedia: jest.fn(),
    PHOTO_CAP: 10, VIDEO_CAP: 3, VIDEO_MAX_DURATION_S: 60,
    PHOTO_MIMES: new Set(["image/jpeg", "image/png", "image/webp", "image/heic"]),
    VIDEO_MIMES: new Set(["video/mp4"]),
    OfflineError,
  };
});

const mockUploadFile = jest.fn();
jest.mock("@/src/api/files", () => ({ uploadFile: (...a: any[]) => mockUploadFile(...a) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/utils/geolocate", () => ({ geolocate: jest.fn(async () => ({ lat: 1, lng: 2, accuracy: 5 })) }));
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "job-1" }),
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), replace: jest.fn() }),
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));

import PhotoUploader from "@/src/components/checklist/PhotoUploader";
import ServiceReportMediaUploader from "@/src/components/checklist/ServiceReportMediaUploader";
import CheckinComposer from "@/app/job/[id]/checkin";

const assets = (n: number, mime = "image/jpeg") =>
  ({ canceled: false, assets: Array.from({ length: n }, (_, i) => ({ uri: `file:///a${i + 1}.jpg`, mimeType: mime, fileName: `a${i + 1}.jpg`, fileSize: 100 })) });
const libOpts = () => mockLaunchLib.mock.calls[0][0];

beforeEach(() => {
  mockLaunchLib.mockReset(); mockLaunchCam.mockReset();
  mockCapture.mockClear(); mockPending.mockReset().mockResolvedValue([]);
  mockSrUpload.mockReset(); mockUploadFile.mockReset();
});

describe("PhotoUploader (checklist Internal Photos)", () => {
  it("3 picked → capturePhoto ×3 in order, selectionLimit = max - count, no allowsEditing, one optimistic refresh", async () => {
    mockLaunchLib.mockResolvedValue(assets(3));
    mockPending.mockResolvedValue([1, 2, 3].map((n) => ({ id: `pending-${n}`, local_uri: `file:///a${n}.jpg` })));
    const onChange = jest.fn();
    const q = render(<PhotoUploader jobId="job-1" photos={[{ id: "p0", url: "u" }, { id: "p00", url: "u" }]} onPhotosChange={onChange} max={10} />);
    await act(async () => { fireEvent.press(q.getByTestId("checklist-photo-library")); });
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(libOpts()).toMatchObject({ allowsMultipleSelection: true, selectionLimit: 8 });
    expect(libOpts()).not.toHaveProperty("allowsEditing");
    expect(mockCapture.mock.calls.map((c) => c[0])).toEqual(["file:///a1.jpg", "file:///a2.jpg", "file:///a3.jpg"]);
    expect(mockPending).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].map((p: any) => p.id)).toEqual(["p0", "p00", "pending-1", "pending-2", "pending-3"]);
  });

  it("at cap → no Library button (existing behaviour), picker never opens; cancel → no change", async () => {
    const full = Array.from({ length: 3 }, (_, i) => ({ id: `p${i}`, url: "u" }));
    const q = render(<PhotoUploader jobId="job-1" photos={full} onPhotosChange={jest.fn()} max={3} />);
    expect(q.queryByTestId("checklist-photo-library")).toBeNull();
    expect(mockLaunchLib).not.toHaveBeenCalled();

    mockLaunchLib.mockResolvedValue({ canceled: true, assets: null });
    const onChange = jest.fn();
    const q2 = render(<PhotoUploader jobId="job-1" photos={[]} onPhotosChange={onChange} max={10} />);
    await act(async () => { fireEvent.press(q2.getByTestId("checklist-photo-library")); });
    expect(mockCapture).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("camera path stays single-shot (launchCameraAsync, allowsEditing kept)", async () => {
    mockLaunchCam.mockResolvedValue(assets(1));
    const q = render(<PhotoUploader jobId="job-1" photos={[]} onPhotosChange={jest.fn()} />);
    await act(async () => { fireEvent.press(q.getByTestId("checklist-photo-camera")); });
    expect(mockLaunchCam).toHaveBeenCalledWith({ quality: 0.7, allowsEditing: true });
    expect(mockLaunchLib).not.toHaveBeenCalled();
    expect(mockCapture).toHaveBeenCalledTimes(1);
  });
});

describe("ServiceReportMediaUploader (Visit Media photos)", () => {
  const mount = (photos: any[] = [], onPhotosChange = jest.fn()) =>
    render(<ServiceReportMediaUploader reportId="sr-1" photos={photos} videos={[]} onPhotosChange={onPhotosChange} onVideosChange={jest.fn()} />);

  it("3 picked → upload ×3; every upload lands (accumulated list), selectionLimit = PHOTO_CAP - count", async () => {
    mockLaunchLib.mockResolvedValue(assets(3));
    mockSrUpload.mockImplementation(async ({ fileUri }: any) => ({ url: `https://cdn/${fileUri.split("/").pop()}` }));
    const onChange = jest.fn();
    const q = mount([{ url: "https://cdn/old.jpg", kind: "photo" }], onChange);
    await act(async () => { fireEvent.press(q.getByTestId("svc-report-photo-library")); });
    await waitFor(() => expect(mockSrUpload).toHaveBeenCalledTimes(3));
    expect(libOpts()).toMatchObject({ allowsMultipleSelection: true, selectionLimit: 9, mediaTypes: ["images"], quality: 0.7 });
    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(last.map((m: any) => m.url)).toEqual(["https://cdn/old.jpg", "https://cdn/a1.jpg", "https://cdn/a2.jpg", "https://cdn/a3.jpg"]);
  });

  it("unsupported MIME in the batch is skipped with the existing error; the rest upload", async () => {
    mockLaunchLib.mockResolvedValue({ canceled: false, assets: [
      { uri: "file:///a1.jpg", mimeType: "image/jpeg" }, { uri: "file:///b.gif", mimeType: "image/gif" }, { uri: "file:///a3.jpg", mimeType: "image/jpeg" },
    ] });
    mockSrUpload.mockResolvedValue({ url: "https://cdn/x.jpg" });
    const q = mount();
    await act(async () => { fireEvent.press(q.getByTestId("svc-report-photo-library")); });
    await waitFor(() => expect(mockSrUpload).toHaveBeenCalledTimes(2));
    expect(q.getByText("Unsupported format: image/gif. Use JPG, PNG, WebP, or HEIC.")).toBeTruthy();
  });

  it("at cap → existing 'Limit reached' alert, picker NOT opened", async () => {
    const { Alert } = require("react-native");
    const spy = jest.spyOn(Alert, "alert").mockImplementation(() => {});
    const full = Array.from({ length: 10 }, (_, i) => ({ url: `u${i}`, kind: "photo" }));
    const q = mount(full);
    await act(async () => { fireEvent.press(q.getByTestId("svc-report-photo-library")); });
    expect(spy).toHaveBeenCalledWith("Limit reached", "Maximum 10 photos per visit.");
    expect(mockLaunchLib).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("Check-in composer (cap 5)", () => {
  it("3 picked → 3 slots, uploadFile ×3, each slot gets its own fileId (no stale index)", async () => {
    mockLaunchLib.mockResolvedValue(assets(3));
    let n = 0;
    mockUploadFile.mockImplementation(async () => ({ id: `f${++n}` }));
    const q = render(<CheckinComposer />);
    await act(async () => { fireEvent.press(q.getByTestId("checkin-photo-library-btn")); });
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(3));
    expect(libOpts()).toMatchObject({ allowsMultipleSelection: true, selectionLimit: 5 });
    expect(mockUploadFile.mock.calls.map((c) => c[0].uri)).toEqual(["file:///a1.jpg", "file:///a2.jpg", "file:///a3.jpg"]);
    await waitFor(() => q.getByTestId("checkin-photo-thumb-2"));
    expect(q.queryByTestId("checkin-photo-thumb-3")).toBeNull();
    expect(q.queryByTestId("checkin-photo-retry-0")).toBeNull();
  });

  it("second pick uses the remaining cap (5 - 3 = 2); a failed upload marks only its own slot", async () => {
    mockLaunchLib.mockResolvedValueOnce(assets(3)).mockResolvedValueOnce(assets(2));
    mockUploadFile
      .mockResolvedValueOnce({ id: "f1" }).mockResolvedValueOnce({ id: "f2" }).mockResolvedValueOnce({ id: "f3" })
      .mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({ id: "f5" });
    const q = render(<CheckinComposer />);
    await act(async () => { fireEvent.press(q.getByTestId("checkin-photo-library-btn")); });
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(3));
    await act(async () => { fireEvent.press(q.getByTestId("checkin-photo-library-btn")); });
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledTimes(5));
    expect(mockLaunchLib.mock.calls[1][0].selectionLimit).toBe(2);
    await waitFor(() => q.getByTestId("checkin-photo-retry-3"));
    expect(q.queryByTestId("checkin-photo-retry-4")).toBeNull();
    // at cap (5/5) → add buttons hidden (existing behaviour)
    expect(q.queryByTestId("checkin-photo-library-btn")).toBeNull();
  });
});

describe("Job detail (source-level — screen too heavy to mount)", () => {
  const SRC = fs.readFileSync(path.resolve(__dirname, "../app/job/[id].tsx"), "utf8");
  const pick = SRC.slice(SRC.indexOf("const pickPhoto = async"), SRC.indexOf("const removePhoto"));
  it("library uses pickImagesMulti with MAX_PHOTOS - photoCount and loops capturePhoto over every uri", () => {
    expect(pick).toMatch(/pickImagesMulti\(\{\s*remainingCap:\s*MAX_PHOTOS - photoCount/);
    expect(pick).toMatch(/for \(const rawUri of uris\)[\s\S]{0,80}capturePhoto\(rawUri/);
    expect(pick).not.toMatch(/launchImageLibraryAsync/);
    expect(pick).toMatch(/launchCameraAsync\(opts\)/); // camera single-shot
  });
});
