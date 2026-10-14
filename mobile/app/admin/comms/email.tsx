// P2 #11 mobile parity — drawer "Email Builder" (web /admin/comms/email)
// opens the native comms template library (view + preview + test-send).
// Editing on mobile is deferred — see memory/TECH_DEBT.md TD-48.
import { Redirect } from "expo-router";

export default function AdminCommsEmailRoute() {
  return <Redirect href="/comms/templates" />;
}
