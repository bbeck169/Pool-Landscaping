#!/usr/bin/env bash
# =============================================================================
# PROD_SMOKE.sh — one-shot post-deploy smoke test for the Pool & Landscaping CRM
# =============================================================================
# Chains all 20 steps from PROD_DEPLOY_CHECKLIST.md into a single run.
# Prints PASS/FAIL per step with color, a summary at the end, and exits 0
# only if every step passes.
#
# Everything is driven by env vars — NO tokens, URLs, or credentials are
# hardcoded. Safe to commit; safe to run against Prod.
#
# Usage:
#   API_BASE=https://<your-prod-domain>/api \
#   ADMIN_EMAIL=admin@example.com \
#   ADMIN_PASSWORD='...' \
#   CUSTOMER_EMAIL=customer@example.com \
#   CUSTOMER_PASSWORD='...' \
#   TENANT_SLUG=your-tenant-slug \
#     ./PROD_SMOKE.sh [--verbose] [--help]
#
# Optional env:
#   TECH_USER_ID     — real tech user id, used by Step 16 (GPS route). If
#                      absent, Step 16 will still PASS as long as the
#                      endpoint returns 200 for a random uid.
#   ROUTE_DATE       — YYYY-MM-DD to query for the GPS route. Defaults to today.
#
# Exit codes:
#   0  — all 20 checks passed
#   1  — one or more checks failed
#   2  — misconfiguration (missing required env var, curl not found, etc.)
# =============================================================================

set -u
set -o pipefail

# ---------- flag parsing --------------------------------------------------
VERBOSE=0
for arg in "$@"; do
  case "$arg" in
    --verbose|-v) VERBOSE=1 ;;
    --help|-h)
      grep -E '^# ' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown flag: $arg (try --help)" >&2 ; exit 2 ;;
  esac
done

# ---------- prereqs -------------------------------------------------------
command -v curl    >/dev/null || { echo "curl not found on PATH" >&2 ; exit 2 ; }
command -v python3 >/dev/null || { echo "python3 not found on PATH" >&2 ; exit 2 ; }

require_env() {
  local name="$1"
  local val="${!name-}"
  if [[ -z "$val" ]]; then
    echo "Missing required env var: $name (see --help)" >&2
    exit 2
  fi
}
require_env API_BASE
require_env ADMIN_EMAIL
require_env ADMIN_PASSWORD
require_env CUSTOMER_EMAIL
require_env CUSTOMER_PASSWORD
require_env TENANT_SLUG

API_BASE="${API_BASE%/}"   # strip trailing slash
ROUTE_DATE="${ROUTE_DATE:-$(date -u +%Y-%m-%d)}"
TECH_USER_ID="${TECH_USER_ID:-nonexistent-user}"

# ---------- pretty printing ----------------------------------------------
if [[ -t 1 ]]; then
  C_G=$'\033[32m'; C_R=$'\033[31m'; C_Y=$'\033[33m'; C_B=$'\033[1m'; C_0=$'\033[0m'
else
  C_G=""; C_R=""; C_Y=""; C_B=""; C_0=""
fi

PASS_COUNT=0
FAIL_COUNT=0
FAILED_STEPS=()

record_pass() {
  PASS_COUNT=$((PASS_COUNT+1))
  printf "  %sPASS%s  Step %2d · %s\n" "$C_G" "$C_0" "$1" "$2"
}
record_fail() {
  FAIL_COUNT=$((FAIL_COUNT+1))
  FAILED_STEPS+=("Step $1: $2")
  printf "  %sFAIL%s  Step %2d · %s — %s\n" "$C_R" "$C_0" "$1" "$2" "$3"
  if [[ "$VERBOSE" -eq 1 && -n "${4-}" ]]; then
    printf "        %sbody:%s %s\n" "$C_Y" "$C_0" "$4"
  fi
}

# ---------- curl helpers --------------------------------------------------
# Emits "HTTP=<code>|BODY=<body>" so we can parse both without a tmp file.
curl_with_code() {
  # $1 = method (GET/POST/etc.), $2 = path (starting with /), rest = extra args
  local method="$1" ; shift
  local path="$1"   ; shift
  local url="${API_BASE}${path}"
  local out
  out=$(curl -sS -o /tmp/psmoke.body -w '%{http_code}' -X "$method" "$url" "$@" || echo "000")
  local body
  body=$(cat /tmp/psmoke.body 2>/dev/null || true)
  printf 'HTTP=%s|BODY=%s' "$out" "$body"
}

http_code() { sed -n 's/^HTTP=\([0-9]\{3\}\).*/\1/p' <<<"$1" ; }
body_of()   { sed -n 's/^HTTP=[0-9]\{3\}|BODY=//p' <<<"$1" ; }

json_get() {
  # $1 = body, $2 = python expression against the parsed dict "d"
  python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print($2)
except Exception as e:
    print('__parse_error__:'+type(e).__name__)
" <<<"$1"
}

# ---------- header --------------------------------------------------------
printf "%sPool & Landscaping — Post-Deploy Smoke Test%s\n" "$C_B" "$C_0"
printf "  API_BASE      : %s\n" "$API_BASE"
printf "  ADMIN_EMAIL   : %s\n" "$ADMIN_EMAIL"
printf "  CUSTOMER_EMAIL: %s\n" "$CUSTOMER_EMAIL"
printf "  TENANT_SLUG   : %s\n" "$TENANT_SLUG"
printf "  ROUTE_DATE    : %s\n\n" "$ROUTE_DATE"

# =========================================================================
# STEP 1 — Health check (openapi.json has at least 400 paths).
# =========================================================================
STEP=1 ; NAME="Health check"
r=$(curl_with_code GET "/openapi.json")
code=$(http_code "$r") ; body=$(body_of "$r")
paths_count=$(python3 -c "import sys,json;print(len(json.loads(sys.stdin.read()).get('paths',{})))" <<<"$body" 2>/dev/null || echo 0)
if [[ "$code" == "200" && "$paths_count" -ge 400 ]]; then
  record_pass "$STEP" "$NAME (paths=$paths_count)"
else
  record_fail "$STEP" "$NAME" "http=$code paths=$paths_count" "${body:0:200}"
fi

# =========================================================================
# STEP 2 — Login as admin & cache JWT.
# =========================================================================
STEP=2 ; NAME="Admin login"
r=$(curl_with_code POST "/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}")
code=$(http_code "$r") ; body=$(body_of "$r")
TOKEN=$(json_get "$body" 'd.get("access_token","")')
if [[ "$code" == "200" && -n "$TOKEN" && "$TOKEN" != __parse_error__* ]]; then
  record_pass "$STEP" "$NAME (token cached)"
else
  record_fail "$STEP" "$NAME — cannot continue without token" "http=$code" "${body:0:200}"
  # Print summary and exit early — the remaining steps depend on TOKEN.
  printf "\n%sABORT%s: admin login failed. Skipping remaining 18 checks.\n" "$C_R" "$C_0"
  printf "\n%sSummary%s\n  PASSED: %d / 20\n  FAILED: %d\n" "$C_B" "$C_0" "$PASS_COUNT" "$FAIL_COUNT"
  exit 1
fi
AUTH=("-H" "Authorization: Bearer ${TOKEN}")

# =========================================================================
# STEP 3 — P1 · client-errors router alive.
# =========================================================================
STEP=3 ; NAME="P1 client-errors router"
r=$(curl_with_code GET "/admin/client-errors?limit=1" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_items=$(json_get "$body" '"items" in d or "errors" in d')
if [[ "$code" == "200" && "$has_items" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 4 — P2 · live GPS positions endpoint alive.
# =========================================================================
STEP=4 ; NAME="P2 live GPS positions"
r=$(curl_with_code GET "/gps/live-positions" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_positions=$(json_get "$body" '"positions" in d')
if [[ "$code" == "200" && "$has_positions" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 5 — Task 5 · payments summary tile.
# =========================================================================
STEP=5 ; NAME="Payments summary"
r=$(curl_with_code GET "/payments/summary" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
if [[ "$code" == "200" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 6 — PB1 · profit report loads.
# Endpoint is `/reports/profit` (no `/admin/` prefix) and requires
# `dimension` + `range` query params.
# =========================================================================
STEP=6 ; NAME="Profit report"
r=$(curl_with_code GET "/reports/profit?dimension=service_category&range=this_month" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
if [[ "$code" == "200" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 7 — G0/G1 · GPS settings admin.
# =========================================================================
STEP=7 ; NAME="GPS settings admin"
r=$(curl_with_code GET "/admin/gps/settings" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_enabled=$(json_get "$body" '"enabled" in d')
if [[ "$code" == "200" && "$has_enabled" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 8 — MR0 · moderation queue admin.
# =========================================================================
STEP=8 ; NAME="Moderation queue"
r=$(curl_with_code GET "/admin/moderation/public-checkins?state=pending_review" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_items=$(json_get "$body" '"items" in d')
if [[ "$code" == "200" && "$has_items" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 9 — MR1 · public widget feed + MR2 · widget.js script.
# Feed path is `/public/checkins/{tenant_slug}/feed` (path param, not query).
# widget.js is served under `/api/widget.js` on the backend origin.
# =========================================================================
STEP=9 ; NAME="Public widget feed + widget.js"
r1=$(curl_with_code GET "/public/checkins/${TENANT_SLUG}/feed?limit=5")
code1=$(http_code "$r1") ; body1=$(body_of "$r1")
has_items=$(json_get "$body1" '"checkins" in d or "items" in d')
r2_code=$(curl -sS -o /tmp/psmoke.js -w '%{http_code}' "${API_BASE}/widget.js" || echo "000")
js_ok=0
if [[ "$r2_code" == "200" ]] && grep -qE 'function|=>|const|var|Shadow' /tmp/psmoke.js; then
  js_ok=1
fi
if [[ "$code1" == "200" && "$has_items" == "True" && "$js_ok" -eq 1 ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "feed_http=$code1 items=$has_items widget_http=$r2_code js_ok=$js_ok" "${body1:0:200}"
fi

# =========================================================================
# STEP 10 — MR-QoL · bulk moderation endpoints alive.
# =========================================================================
STEP=10 ; NAME="Moderation bulk-approve"
r=$(curl_with_code POST "/admin/moderation/public-checkins/bulk-approve" \
  "${AUTH[@]}" -H "Content-Type: application/json" -d '{"ids":["nonexistent"]}')
code=$(http_code "$r") ; body=$(body_of "$r")
has_shape=$(json_get "$body" '"approved" in d or "skipped" in d')
if [[ "$code" == "200" && "$has_shape" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 11 — SEO-A · on-page auditor scan.
# =========================================================================
STEP=11 ; NAME="SEO auditor scan"
r=$(curl_with_code POST "/seo/scans" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d '{"target_url":"https://example.com","async":false}')
code=$(http_code "$r") ; body=$(body_of "$r")
has_results=$(json_get "$body" '"results" in d or "scan_id" in d')
if [[ "$code" == "200" && "$has_results" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 12 — SEO-B · outreach pipeline counts.
# =========================================================================
STEP=12 ; NAME="Outreach pipeline"
r=$(curl_with_code GET "/outreach/pipeline" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_total=$(json_get "$body" '"total" in d or "pending" in d')
if [[ "$code" == "200" && "$has_total" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 13 — SEO-B · outreach cron fires on demand.
# =========================================================================
STEP=13 ; NAME="Outreach followup cron"
r=$(curl_with_code POST "/outreach/cron/followup-digest" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_shape=$(json_get "$body" '"tenants_scanned" in d or "digests_sent" in d')
if [[ "$code" == "200" && "$has_shape" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 14 — SEO-C · keyword ideation runs.
# =========================================================================
STEP=14 ; NAME="Keyword ideation"
r=$(curl_with_code POST "/keywords/ideate" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d '{"seed_keyword":"pool service phoenix"}')
code=$(http_code "$r") ; body=$(body_of "$r")
has_sugg=$(json_get "$body" '"autocomplete_suggestions" in d')
if [[ "$code" == "200" && "$has_sugg" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 15 — Sidebar visual smoke (proxy via a customer login round-trip).
# We can't drive a real browser from bash, so we approximate by verifying
# the customer credentials pair works — a common regression signal that
# the auth layer + tenant routing survived the deploy.
# =========================================================================
STEP=15 ; NAME="Customer login round-trip (sidebar smoke proxy)"
r=$(curl_with_code POST "/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${CUSTOMER_EMAIL}\",\"password\":\"${CUSTOMER_PASSWORD}\"}")
code=$(http_code "$r") ; body=$(body_of "$r")
cust_token=$(json_get "$body" 'd.get("access_token","")')
if [[ "$code" == "200" && -n "$cust_token" && "$cust_token" != __parse_error__* ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code" "${body:0:200}"
fi

# =========================================================================
# STEP 16 — G4 + G5c · GPS route rendering with playback_duration_s.
# Endpoint takes `from`/`to` (ISO datetime) query params, not `date`.
# We probe a 7-day window ending "now" — always safe.
# =========================================================================
STEP=16 ; NAME="GPS route + replay meta"
FROM_ISO=$(python3 -c "from datetime import datetime,timedelta,timezone;print((datetime.now(timezone.utc)-timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
TO_ISO=$(python3   -c "from datetime import datetime,timezone;print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
r=$(curl_with_code GET "/gps/route?user_id=${TECH_USER_ID}&from=${FROM_ISO}&to=${TO_ISO}" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_replay=$(json_get "$body" '"playback_duration_s" in d')
if [[ "$code" == "200" && "$has_replay" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http=$code playback_duration_s=$has_replay" "${body:0:200}"
fi

# =========================================================================
# STEP 17 — G3 · reverse-geocode wire status.
# =========================================================================
STEP=17 ; NAME="Reverse-geocode wire status"
r=$(curl_with_code GET "/admin/gps/settings" "${AUTH[@]}")
code=$(http_code "$r") ; body=$(body_of "$r")
has_field=$(json_get "$body" '"mapbox_token_configured" in d')
val=$(json_get   "$body" 'd.get("mapbox_token_configured")')
if [[ "$code" == "200" && "$has_field" == "True" ]]; then
  record_pass "$STEP" "$NAME (mapbox_token_configured=$val)"
else
  record_fail "$STEP" "$NAME" "http=$code has_field=$has_field" "${body:0:200}"
fi

# =========================================================================
# STEP 18 — G5a · geofences + entry/exit events.
# Endpoints are `/geofences` and `/geofence-events` (no `/admin/gps/`).
# =========================================================================
STEP=18 ; NAME="Geofences + entry/exit events"
r1=$(curl_with_code GET "/geofences" "${AUTH[@]}")
c1=$(http_code "$r1") ; b1=$(body_of "$r1")
r2=$(curl_with_code GET "/geofence-events?limit=5" "${AUTH[@]}")
c2=$(http_code "$r2") ; b2=$(body_of "$r2")
has1=$(json_get "$b1" '"items" in d')
has2=$(json_get "$b2" '"items" in d')
if [[ "$c1" == "200" && "$c2" == "200" && "$has1" == "True" && "$has2" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "geofences_http=$c1 events_http=$c2" "${b1:0:100} | ${b2:0:100}"
fi

# =========================================================================
# STEP 19 — G5b · attribution settings + batch runner.
# Batch response uses `processed / auto_linked / no_match / skipped`.
# =========================================================================
STEP=19 ; NAME="Attribution settings + batch"
r1=$(curl_with_code GET "/admin/gps/attribution/settings" "${AUTH[@]}")
c1=$(http_code "$r1") ; b1=$(body_of "$r1")
r2=$(curl_with_code POST "/admin/gps/attribution/run-batch" "${AUTH[@]}")
c2=$(http_code "$r2") ; b2=$(body_of "$r2")
has1=$(json_get "$b1" '"proximity_threshold_m" in d or "same_day_only" in d')
has2=$(json_get "$b2" '"processed" in d or "auto_linked" in d')
if [[ "$c1" == "200" && "$c2" == "200" && "$has1" == "True" && "$has2" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "settings_http=$c1 batch_http=$c2 has1=$has1 has2=$has2" "${b1:0:100} | ${b2:0:100}"
fi

# =========================================================================
# STEP 20 — G5d · driver scorecard leaderboard.
# Response uses `rows[]` and a `range` object. `range=this_week` is the
# canonical short-name; `7d` is not a valid enum on this build. We verify
# the endpoint returns 200 twice in a row (cache warm signal — second
# call should not error out).
# =========================================================================
STEP=20 ; NAME="Driver Scorecard leaderboard"
r1=$(curl_with_code GET "/admin/gps/scorecard/leaderboard?range=this_week" "${AUTH[@]}")
c1=$(http_code "$r1") ; b1=$(body_of "$r1")
has_rows=$(json_get "$b1" '"rows" in d')
r2=$(curl_with_code GET "/admin/gps/scorecard/leaderboard?range=this_week" "${AUTH[@]}")
c2=$(http_code "$r2")
if [[ "$c1" == "200" && "$c2" == "200" && "$has_rows" == "True" ]]; then
  record_pass "$STEP" "$NAME"
else
  record_fail "$STEP" "$NAME" "http1=$c1 http2=$c2 has_rows=$has_rows" "${b1:0:200}"
fi

# =========================================================================
# Summary
# =========================================================================
printf "\n%sSummary%s\n" "$C_B" "$C_0"
printf "  PASSED: %s%d%s / 20\n" "$C_G" "$PASS_COUNT" "$C_0"
printf "  FAILED: %s%d%s\n"       "$C_R" "$FAIL_COUNT" "$C_0"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  printf "\n%sFailed steps:%s\n" "$C_R" "$C_0"
  for line in "${FAILED_STEPS[@]}"; do
    printf "  · %s\n" "$line"
  done
  exit 1
fi

printf "\n%sAll 20 checks passed — deploy is healthy.%s\n" "$C_G" "$C_0"
exit 0
