/**
 * Phase Hygiene B · Feb-2026 — global jest setup.
 *
 * Registers a project-wide mock for @react-native-async-storage/async-storage
 * so any component that transitively pulls it in (auth token persistence,
 * cache layer, feature flags, etc.) can mount inside jest-expo without
 * hitting "NativeModule: AsyncStorage is null". The package ships a
 * ready-made mock; wiring it here means individual test files don't have
 * to remember to mock it themselves.
 */
jest.mock(
  "@react-native-async-storage/async-storage",
  () => require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);
