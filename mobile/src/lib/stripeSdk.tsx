/**
 * stripeSdk.tsx — Native re-export of @stripe/stripe-react-native.
 *
 * On native builds (iOS/Android), this re-exports the real SDK.
 * Metro picks this file for native platforms and stripeSdk.web.tsx for web.
 */
export {
  StripeProvider,
  initPaymentSheet,
  presentPaymentSheet,
} from "@stripe/stripe-react-native";
