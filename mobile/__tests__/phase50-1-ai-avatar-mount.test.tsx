/**
 * Phase 50.1 · Feb-2026 — Mobile <AIAvatar> image overlay parity.
 *
 * Confirms that:
 *   - When ``src`` is provided (from a persona's ``avatar_url``),
 *     the mobile ``<AIAvatar>`` composes BOTH the ``<LottieView>``
 *     backdrop AND the static ``<Image>``.
 *   - When ``src`` is null / undefined, only the ``<LottieView>``
 *     renders (no ``<Image>`` -> no broken-image icon).
 *
 * ``lottie-react-native`` is a native module → stubbed so jest can
 * mount it under jsdom / node.
 */
import React from "react";
import { render } from "@testing-library/react-native";

// Stub the native Lottie module — tag its output with a distinct
// testID so we can assert both layers cleanly.
jest.mock("lottie-react-native", () => {
  const { View } = require("react-native");
  return {
    __esModule: true,
    default: (props: any) => <View testID="lottie-backdrop" {...props} />,
  };
});

// eslint-disable-next-line import/first
import AIAvatar from "@/src/components/ai/AIAvatar";

describe("Phase 50.1 · Mobile <AIAvatar> parity", () => {
  it("renders BOTH the Lottie backdrop and the static <Image> when src is set", () => {
    const { getByTestId, UNSAFE_getByType } = render(
      <AIAvatar
        src="https://backend.example/avatars/personas/billy.jpg"
        size={52}
        testID="ai-lottie-avatar-billy"
      />,
    );
    // Wrapper carries the requested testID
    expect(getByTestId("ai-lottie-avatar-billy")).toBeTruthy();
    // Lottie backdrop (stubbed)
    expect(getByTestId("lottie-backdrop")).toBeTruthy();
    // Static image on top — look up by native ``Image`` type.
    const { Image } = require("react-native");
    const img = UNSAFE_getByType(Image);
    expect(img.props.source).toEqual({
      uri: "https://backend.example/avatars/personas/billy.jpg",
    });
  });

  it("renders ONLY the Lottie backdrop when src is undefined", () => {
    const { getByTestId, UNSAFE_queryByType } = render(
      <AIAvatar size={52} testID="ai-lottie-avatar-no-image" />,
    );
    expect(getByTestId("ai-lottie-avatar-no-image")).toBeTruthy();
    expect(getByTestId("lottie-backdrop")).toBeTruthy();
    // No <Image> component -> Lottie-only fallback (no broken-image
    // placeholder). Guards the ``avatar_url = null`` backend contract.
    const { Image } = require("react-native");
    expect(UNSAFE_queryByType(Image)).toBeNull();
  });
});
