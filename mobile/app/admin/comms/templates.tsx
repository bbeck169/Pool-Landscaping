// P2 #11 mobile parity — drawer "Templates" (web /admin/comms/templates)
// opens the native comms template library.
import { Redirect } from "expo-router";

export default function AdminCommsTemplatesRoute() {
  return <Redirect href="/comms/templates" />;
}
