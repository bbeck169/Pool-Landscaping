/**
 * TD-88e · pickImagesMulti — shared multi-select library picker.
 */
const mockReqPerm = jest.fn();
const mockLaunch = jest.fn();
jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: (...a: any[]) => mockReqPerm(...a),
  launchImageLibraryAsync: (...a: any[]) => mockLaunch(...a),
}));

import { pickImagesMulti } from "@/src/lib/pickImages";

const asset = (n: number) => ({ uri: `file:///p${n}.jpg`, width: 10, height: 10, mimeType: "image/jpeg" });
const picked = (n: number) => ({ canceled: false, assets: Array.from({ length: n }, (_, i) => asset(i + 1)) });

beforeEach(() => {
  mockReqPerm.mockReset().mockResolvedValue({ granted: true, canAskAgain: true });
  mockLaunch.mockReset();
});

it("limit=1 → opens multi-select with selectionLimit 1, returns a single-asset array", async () => {
  mockLaunch.mockResolvedValue(picked(1));
  const r = await pickImagesMulti({ remainingCap: 1 });
  expect(r).toEqual([asset(1)]);
  expect(mockLaunch).toHaveBeenCalledWith(expect.objectContaining({ allowsMultipleSelection: true, selectionLimit: 1 }));
});

it("limit=3 → returns up to 3 (trims when the platform ignores selectionLimit, e.g. web)", async () => {
  mockLaunch.mockResolvedValue(picked(3));
  expect(await pickImagesMulti({ remainingCap: 3 })).toHaveLength(3);
  mockLaunch.mockResolvedValue(picked(5));
  const r = await pickImagesMulti({ remainingCap: 3 });
  expect(r?.map((a) => a.uri)).toEqual(["file:///p1.jpg", "file:///p2.jpg", "file:///p3.jpg"]);
  mockLaunch.mockResolvedValue(picked(2));
  expect(await pickImagesMulti({ remainingCap: 3 })).toHaveLength(2);
});

it("limit=0 (or negative / NaN) → does not request permission or open the picker", async () => {
  for (const cap of [0, -2, NaN]) {
    expect(await pickImagesMulti({ remainingCap: cap })).toBeNull();
  }
  expect(mockReqPerm).not.toHaveBeenCalled();
  expect(mockLaunch).not.toHaveBeenCalled();
});

it("cancel → null", async () => {
  mockLaunch.mockResolvedValue({ canceled: true, assets: null });
  expect(await pickImagesMulti({ remainingCap: 4 })).toBeNull();
});

it("empty / uri-less assets → null", async () => {
  mockLaunch.mockResolvedValue({ canceled: false, assets: [{ uri: "" }] });
  expect(await pickImagesMulti({ remainingCap: 4 })).toBeNull();
});

it("permission denied → null, picker not opened", async () => {
  mockReqPerm.mockResolvedValue({ granted: false, canAskAgain: false });
  expect(await pickImagesMulti({ remainingCap: 4 })).toBeNull();
  expect(mockLaunch).not.toHaveBeenCalled();
});

it("passes quality / base64 / mediaTypes through, never allowsEditing; defaults images + 0.7", async () => {
  mockLaunch.mockResolvedValue(picked(1));
  await pickImagesMulti({ remainingCap: 2 });
  const d = mockLaunch.mock.calls[0][0];
  expect(d).toEqual({ allowsMultipleSelection: true, selectionLimit: 2, orderedSelection: true, quality: 0.7, mediaTypes: ["images"] });
  await pickImagesMulti({ remainingCap: 2, quality: 0.4, base64: true, mediaTypes: ["images", "livePhotos"] });
  const o = mockLaunch.mock.calls[1][0];
  expect(o).toMatchObject({ quality: 0.4, base64: true, mediaTypes: ["images", "livePhotos"] });
  expect(o).not.toHaveProperty("allowsEditing");
});
