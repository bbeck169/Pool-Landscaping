/**
 * Phase 50 · Feb-2026 — Animated AI-employee avatar (web).
 *
 * Shared Lottie idle loop (blink + subtle breathing scale) rendered
 * behind a small circular badge that echoes the employee's static
 * ``avatar_url``. Lottie file at ``src/assets/lottie/ai/idle.json``
 * is hand-crafted — MIT-licensed by the repo, no third-party asset.
 */
import React from "react";
import Lottie from "lottie-react";
import idle from "@/assets/lottie/ai/idle.json";

export default function AIAvatar({ src, alt = "", size = 64, testId }) {
  return (
    <div
      className="relative inline-block rounded-full overflow-hidden"
      style={{ width: size, height: size }}
      data-testid={testId || "ai-lottie-avatar"}
    >
      <Lottie
        animationData={idle}
        loop
        autoplay
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        aria-hidden="true"
      />
      {src ? (
        <img
          src={src}
          alt={alt}
          style={{
            position: "absolute", inset: "18%", width: "64%", height: "64%",
            borderRadius: "50%", objectFit: "cover",
          }}
        />
      ) : null}
    </div>
  );
}
