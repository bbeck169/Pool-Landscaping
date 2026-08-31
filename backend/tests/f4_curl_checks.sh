#!/usr/bin/env bash
# F4 · Widget-Embed Check-ins Map — curl-driven smoke suite (5 checks)
set -uo pipefail
BASE=$(grep '^REACT_APP_BACKEND_URL=' /app/frontend/.env | cut -d= -f2- | tr -d '\r')
echo "BASE=$BASE"
PASS=0; FAIL=0
ok(){ echo "  PASS: $1"; PASS=$((PASS+1)); }
no(){ echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

echo "=== 1) GET /api/public/checkins/aquaterra/pins ==="
CODE=$(curl -s -o /tmp/pins.json -w '%{http_code}' "$BASE/api/public/checkins/aquaterra/pins")
echo "  status=$CODE"
[ "$CODE" = "200" ] && ok "pins 200" || no "pins expected 200 got $CODE"
cat /tmp/pins.json | head -c 1200; echo
for k in tenant pins count as_of window_days; do
  jq -e "has(\"$k\")" /tmp/pins.json >/dev/null 2>&1 && ok "top-level key $k" || no "missing top-level key $k"
done
PINCOUNT=$(jq '.pins|length' /tmp/pins.json 2>/dev/null)
echo "  pins length=$PINCOUNT  count=$(jq '.count' /tmp/pins.json 2>/dev/null)"
EXTRA=$(jq -r '[.pins[]|keys[]]|unique - ["lat","lng","service_type","completed_at_month_year","area_label"]|join(",")' /tmp/pins.json 2>/dev/null)
if [ -z "$EXTRA" ]; then ok "pin dicts contain ONLY allowed keys"; else no "unexpected pin keys: $EXTRA"; fi
MISSING=$(jq -r '["lat","lng","service_type","completed_at_month_year","area_label"] - ([.pins[]|keys[]]|unique)|join(",")' /tmp/pins.json 2>/dev/null)
if [ "$PINCOUNT" -gt 0 ] 2>/dev/null; then
  [ -z "$MISSING" ] && ok "all 5 required pin keys present" || no "pin keys missing: $MISSING"
else no "pins array EMPTY - cannot validate pin shape"; fi
PII=$(grep -o -E 'customer_name|customer_id|job_id|raw_lat|raw_lng|raw_address|masked_address|"lat_public"|"lng_public"|completed_at"' /tmp/pins.json | sort -u | tr '\n' ',')
if [ -z "$PII" ]; then ok "no PII keys in pins body"; else no "PII-ish keys found: $PII"; fi

echo "=== 2) GET /api/public/checkins/aquaterra/map.html ==="
CODE=$(curl -s -o /tmp/map.html -w '%{http_code}' -D /tmp/map.hdr "$BASE/api/public/checkins/aquaterra/map.html")
echo "  status=$CODE ctype=$(grep -i '^content-type' /tmp/map.hdr | tr -d '\r')"
[ "$CODE" = "200" ] && ok "map.html 200" || no "map.html expected 200 got $CODE"
grep -qi 'content-type:.*text/html' /tmp/map.hdr && ok "content-type text/html" || no "content-type not text/html"
grep -q 'unpkg.com/leaflet@1.9.4/dist/leaflet.css' /tmp/map.html && ok "Leaflet CDN css link" || no "no Leaflet CDN css"
grep -q 'unpkg.com/leaflet@1.9.4/dist/leaflet.js' /tmp/map.html && ok "Leaflet CDN js" || no "no Leaflet CDN js"
grep -q 'application/ld+json' /tmp/map.html && ok "ld+json script block present" || no "no ld+json block"
python3 - <<'PY'
import re, json, sys
h = open('/tmp/map.html').read()
m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S)
if not m:
    print("  FAIL: could not extract ld+json"); sys.exit(0)
try:
    d = json.loads(m.group(1))
except Exception as e:
    print("  FAIL: ld+json not valid JSON:", e); sys.exit(0)
print("  ld+json @type =", d.get("@type"))
print("  areaServed n =", len(d.get("areaServed") or []), " makesOffer n =", len(d.get("makesOffer") or []))
print("  PASS: @type LocalBusiness" if d.get("@type")=="LocalBusiness" else "  FAIL: @type is "+str(d.get("@type")))
bad=[k for k in ("customer_name","customer_id","job_id") if k in h]
print("  FAIL: PII in html: "+str(bad) if bad else "  PASS: no PII tokens in map.html")
PY

echo "=== 3) GET /api/public/checkins/nonexistent-slug-xyz/pins ==="
CODE=$(curl -s -o /tmp/404.json -w '%{http_code}' "$BASE/api/public/checkins/nonexistent-slug-xyz/pins")
echo "  status=$CODE body=$(head -c 200 /tmp/404.json)"
[ "$CODE" = "404" ] && ok "unknown slug 404" || no "expected 404 got $CODE"

echo "=== 4) Admin moderation list state=all ==="
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"email":"admin@aquaterra.com","password":"password123"}' | jq -r '.access_token')
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then no "admin login failed"; else ok "admin login"; fi
CODE=$(curl -s -o /tmp/mod.json -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/admin/moderation/public-checkins?state=all&limit=200")
echo "  status=$CODE total=$(jq '.total' /tmp/mod.json 2>/dev/null)"
[ "$CODE" = "200" ] && ok "moderation list 200" || no "moderation list expected 200 got $CODE"
jq -r '.items[]|"    - \(.service_name) | state=\(.state) | source=\(.source)"' /tmp/mod.json 2>/dev/null | head -20
S1=$(jq -r '[.items[]|select(.service_name=="Weekly Pool Cleaning (F4 demo · auto)")|.source]|join(",")' /tmp/mod.json 2>/dev/null)
S2=$(jq -r '[.items[]|select(.service_name=="Palm Tree Trim (F4 demo · tech)")|.source]|join(",")' /tmp/mod.json 2>/dev/null)
[ "$S1" = "auto" ] && ok "demo row auto source=auto" || no "auto demo row source='$S1' (expected auto)"
[ "$S2" = "tech" ] && ok "demo row tech source=tech" || no "tech demo row source='$S2' (expected tech)"
NOID=$(jq -e '[.items[]|has("_id")]|any' /tmp/mod.json >/dev/null 2>&1 && echo yes || echo no)
[ "$NOID" = "no" ] && ok "no mongo _id leaked" || no "_id leaked in moderation list"

echo "=== 5) Regression: widget.js + widget preview ==="
C1=$(curl -s -o /tmp/w.js -w '%{http_code}' "$BASE/api/widget.js")
C2=$(curl -s -o /tmp/wp.html -w '%{http_code}' "$BASE/api/widget/preview/aquaterra")
echo "  widget.js=$C1 ($(wc -c </tmp/w.js) bytes)  preview=$C2 ($(wc -c </tmp/wp.html) bytes)"
[ "$C1" = "200" ] && ok "widget.js 200" || no "widget.js got $C1"
[ "$C2" = "200" ] && ok "widget/preview 200" || no "widget/preview got $C2"

echo "======================================="
echo "PASS=$PASS FAIL=$FAIL"
