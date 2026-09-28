# QA Checklist — FLEET-B (Mobile GPS Emission)

## Prerequisites
- Admin account: `admin@aquaterra.com` / `password123`
- Pool Tech account: `mike@aquaterra.com` / `password123`
- Admin must have enabled the tech for fleet membership via the web admin panel (`/admin/settings/fleet-membership`)

---

## 1. Permission Flow

| # | Step | Expected |
|---|------|----------|
| 1.1 | Log in as tech `mike@aquaterra.com` | Login succeeds |
| 1.2 | Observe Fleet Status Chip in tab bar area | Green "In Fleet" chip if enrolled, or grey "Not in Fleet" if not |
| 1.3 | If prompted for location, grant permission | Chip turns green, emitter starts |
| 1.4 | Deny location permission | Chip shows red "No GPS" |

## 2. GPS Ping Cadence

| # | Step | Expected |
|---|------|----------|
| 2.1 | With app active, watch network requests | POST `/api/fleet/ping` fires every ~15s |
| 2.2 | Lock device screen (or minimize), then return | Pings should have paused while background; resume on foreground return |
| 2.3 | Drain battery below 20% (or mock) | Interval should degrade to 60s active |

## 3. Battery-Aware Degradation

| # | Step | Expected |
|---|------|----------|
| 3.1 | Battery > 20%, app active | 15s interval |
| 3.2 | Battery < 20%, app active | 60s interval |
| 3.3 | Battery < 20%, app idle | No pings (foreground-only) |

## 4. Error Handling

| # | Step | Expected |
|---|------|----------|
| 4.1 | Tech not enrolled in fleet → ping | 403 → emitter stops, chip shows "Not in Fleet" |
| 4.2 | Device time severely skewed | 400 → skip ping, next ping has fresh timestamp |
| 4.3 | Rapid-fire pings < 5s apart | 429 → skipped silently, no error shown |
| 4.4 | Toggle airplane mode ON | Network error → retry once after 5s, then wait for next interval |
| 4.5 | Toggle airplane mode OFF | Pings resume on next interval |

## 5. Manual Check-In (On My Way / Arrived)

| # | Step | Expected |
|---|------|----------|
| 5.1 | Open a job detail screen as tech | "On My Way" and "Arrived" buttons visible |
| 5.2 | Tap "On My Way" | Button shows spinner → success toast ("On my way — customer notified" or similar) → 10s cooldown |
| 5.3 | Tap "On My Way" again immediately | Button disabled during cooldown |
| 5.4 | Tap "Arrived" | Success toast "Arrived — check-in recorded" → 10s cooldown |
| 5.5 | Tech not in fleet → tap either button | Error toast "Not in fleet — ask admin to enable" |

## 6. Fleet Status Chip

| # | Step | Expected |
|---|------|----------|
| 6.1 | Chip visible in tab bar area | Small pill with colored dot + label |
| 6.2 | Tap chip | Modal opens with status description |
| 6.3 | While emitting: chip = green "In Fleet" | Correct |
| 6.4 | After pausing: chip = yellow "Paused" | Correct |
| 6.5 | After stopping: chip = red "Off" | Correct |

## 7. Settings Toggle (Pause)

| # | Step | Expected |
|---|------|----------|
| 7.1 | Navigate to More/Profile screen | "Fleet Tracking" row visible for techs |
| 7.2 | Toggle OFF | Emitter stops, chip shows "Paused" |
| 7.3 | Toggle ON | Emitter restarts, chip shows "In Fleet" |
| 7.4 | Kill and relaunch app with toggle OFF | Emitter stays paused on restart |

## 8. Edge Cases

| # | Step | Expected |
|---|------|----------|
| 8.1 | Log out and log back in | Emitter restarts cleanly |
| 8.2 | Log in as admin | Fleet chip visible but emitter does NOT start (admin is not a tech) |
| 8.3 | Log in as customer | Fleet chip NOT visible |
| 8.4 | Switch between tabs rapidly | No crash, no duplicate emitters |

---

## Not Tested (Out of Scope)
- Background location tracking (FLEET-B is foreground-only)
- Background task registration
- Push notification for fleet events
