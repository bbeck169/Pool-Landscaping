/**
 * Phase 31 · Step 2c hotfix — Metro alias + platform-extension barrel.
 *
 * The two variants `MapCanvas.native.tsx` / `MapCanvas.web.tsx` exist
 * side-by-side and Metro's platform-extension resolver picks the right
 * one when the import specifier ends in the bare name. HOWEVER, when
 * the specifier goes through the `@/*` tsconfig path alias, Metro
 * resolves the alias FIRST and then looks for an exact-suffix match —
 * missing the `.native.tsx` / `.web.tsx` variants. Symptom: Expo Web
 * bundler 500 with `Unable to resolve module @/src/components/d2d/MapCanvas`.
 *
 * This barrel lives at the alias-resolved path (`MapCanvas.tsx`) and
 * re-dispatches to the correct platform variant at load-time. Both
 * variants get compiled — that's fine, the web one is a ~20-line
 * placeholder and the native one wraps `react-native-maps`.
 */
import { Platform } from "react-native";

// eslint-disable-next-line @typescript-eslint/no-var-requires
const impl = Platform.OS === "web"
  ? require("./MapCanvas.web").default
  : require("./MapCanvas.native").default;

export default impl;
