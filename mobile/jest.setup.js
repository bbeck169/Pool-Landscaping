/**
 * Phase Hygiene B · Feb-2026 — global jest setup.
 *
 * Registers a project-wide mock for @react-native-async-storage/async-storage
 * so any component that transitively pulls it in (auth token persistence,
 * cache layer, feature flags, etc.) can mount inside jest-expo without
 * hitting "NativeModule: AsyncStorage is null". The package ships a
 * ready-made mock; wiring it here means individual test files don't have
 * to remember to mock it themselves.
 *
 * Also stubs @react-native-community/netinfo — several data-fetch layers
 * subscribe to ``NetInfo.addEventListener`` and read
 * ``NetInfo.fetch().isInternetReachable`` at boot. The NativeModule
 * isn't present under jest-expo, so the default subscription blows up
 * with ``Cannot read properties of undefined (reading
 * 'isInternetReachable')``. Return a stable "online" state.
 */
jest.mock(
  "@react-native-async-storage/async-storage",
  () => require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

jest.mock("@react-native-community/netinfo", () => ({
  __esModule: true,
  default: {
    fetch: jest.fn().mockResolvedValue({
      type: "wifi",
      isConnected: true,
      isInternetReachable: true,
      details: null,
    }),
    addEventListener: jest.fn(() => () => {}),
    useNetInfo: () => ({
      type: "wifi",
      isConnected: true,
      isInternetReachable: true,
      details: null,
    }),
    refresh: jest.fn().mockResolvedValue({
      type: "wifi",
      isConnected: true,
      isInternetReachable: true,
      details: null,
    }),
    configure: jest.fn(),
  },
  fetch: jest.fn().mockResolvedValue({
    type: "wifi",
    isConnected: true,
    isInternetReachable: true,
    details: null,
  }),
  addEventListener: jest.fn(() => () => {}),
  useNetInfo: () => ({
    type: "wifi",
    isConnected: true,
    isInternetReachable: true,
    details: null,
  }),
  refresh: jest.fn().mockResolvedValue({
    type: "wifi",
    isConnected: true,
    isInternetReachable: true,
    details: null,
  }),
  configure: jest.fn(),
}));
