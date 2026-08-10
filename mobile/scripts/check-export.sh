#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# check-export.sh — Local `expo export` smoke test.
#
# Reproduces the Cloud Build Step #9 (`eas-update`) bundle path so
# regressions in the walkie/react-native-webrtc chain (or any other
# static-resolver footgun via expo-router's `require.context`) are
# caught locally BEFORE they trip the deploy pipeline.
#
# Root cause of the historical failure: react-native-webrtc@124
# imports "event-target-shim/index", a deep specifier absent from
# event-target-shim's `exports` map. Metro's fast resolver enforces
# the exports map strictly. The fix lives in `metro.config.js` as a
# `resolveRequest` override; this script guards it.
#
# Usage:
#     bash scripts/check-export.sh                # both platforms
#     bash scripts/check-export.sh ios            # single platform
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

cd "$(dirname "$0")/.."

PLATFORMS=("${@:-ios android}")
# When invoked with no args, "${@:-ios android}" expands to two
# tokens ("ios" "android") inside the array literal via word-split.
if [ "$#" -eq 0 ]; then
  PLATFORMS=(ios android)
fi

OUT_ROOT="${EXPO_EXPORT_SMOKE_DIR:-/tmp/expo-export-smoke}"
rm -rf "$OUT_ROOT"

FAILED=()
for PLAT in "${PLATFORMS[@]}"; do
  echo ""
  echo "──────────────────────────────────────────────────────────────"
  echo "  expo export smoke · platform=${PLAT}"
  echo "──────────────────────────────────────────────────────────────"
  OUT="${OUT_ROOT}/${PLAT}"
  # `--dev` keeps the bundle un-minified (faster) but still exercises
  # the full resolver walk, which is what actually breaks in CI.
  if npx --no-install expo export \
        --platform "$PLAT" \
        --output-dir "$OUT" \
        --dev; then
    echo "✔ ${PLAT} export ok"
  else
    echo "✗ ${PLAT} export FAILED"
    FAILED+=("$PLAT")
  fi
done

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo ""
  echo "check-export.sh FAILED for: ${FAILED[*]}"
  exit 1
fi

echo ""
echo "check-export.sh ok · all platforms exported cleanly."
