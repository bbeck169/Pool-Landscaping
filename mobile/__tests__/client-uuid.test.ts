/**
 * Phase O2 · clientUuid — crypto-strong UUID v4 tests.
 */

// Mock the polyfill — Node.js has crypto natively so uuid works in Jest.
jest.mock("react-native-get-random-values", () => {});

import { clientUuid } from "@/src/services/ids/clientUuid";

const UUID_V4_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe("clientUuid (Phase O2)", () => {
  it("returns a valid RFC-4122 v4 UUID", () => {
    const id = clientUuid();
    expect(id).toMatch(UUID_V4_RE);
  });

  it("1000 iterations produce zero collisions", () => {
    const set = new Set<string>();
    for (let i = 0; i < 1000; i++) set.add(clientUuid());
    expect(set.size).toBe(1000);
  });

  it("does not use Math.random in the generator path", () => {
    const spy = jest.spyOn(Math, "random");
    clientUuid();
    clientUuid();
    clientUuid();
    // uuid v11 + react-native-get-random-values uses crypto, not Math.random
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
