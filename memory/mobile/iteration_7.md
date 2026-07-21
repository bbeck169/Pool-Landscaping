# Iteration 7 — AI Dock Bug Fix (Identifier Mismatch)

## Problem
Mobile AI Dock returned "AI employee not found" when sending messages. Root cause: Mobile used a legacy `POST /api/ai-employees/chat` endpoint expecting string slugs (`key` field like "buddy"), while the backend's actual conversation flow uses UUID-based endpoints.

## Root Cause
The previous `aiDock.ts` had a `chatSimple(key, text)` function calling `POST /api/ai-employees/chat` with `{ employee: key, text }`. This endpoint either didn't exist or expected the `key` field to be a UUID `id`. The web frontend uses the proper conversation-based flow:
1. `POST /api/ai-employees/{eid}/conversations` — create conversation (eid = UUID)
2. `POST /api/ai-employees/{eid}/conversations/{cid}/messages` — send message

## Changes Made

### `/app/mobile/src/api/aiDock.ts`
- Removed legacy `chatSimple` function
- Added: `createConversation(eid, title?)`, `sendConversationMessage(eid, cid, text, action?, actionParams?)`, `listConversations(eid)`, `getMessages(eid, cid)`, `listPendingActions(employeeKey?)`, `approveAction(aid)`, `rejectAction(aid)`
- All endpoints match the web frontend's API usage exactly

### `/app/mobile/src/components/ai/AIDockDrawer.tsx`
- Rewrote `ChatView` to manage conversation state (`convId`)
- On mount: creates a new conversation via `createConversation(employee.id, ...)`
- Send: uses `sendConversationMessage(employee.id, convId, text)`
- Response handling: parses `{ user_message, assistant_message, action? }` shape
- Pending actions: loaded per-employee and displayed with Approve/Discard buttons
- Fixed action card display: `a.label || a.action_type` → `a.title || a.action`, `a.description` → `a.summary` (matching backend schema)

## Verification (Screenshot Tests)
1. Basic chat: Sent "Hello Buddy, how are you?" → Received full AI response (no error)
2. Action trigger: Sent "Give me a weekly growth brief" → Buddy returned comprehensive Weekly Growth Brief with Pipeline Win Rate, InstaQuote Conversion sections
3. Approve flow: Clicked Approve on pending action → Count dropped from 14 to 13, action removed
4. Credits: Balance decremented correctly (3741c → 3740c after message)
5. Pending actions display: Titles rendered correctly ("Weekly growth brief — 7d", "Pricing recommendation")

## Known Items
- Each chat session creates a new conversation (no conversation persistence/selection yet). This matches the basic web flow.
- The `action` parameter in `sendConversationMessage` is optional — natural language messages go through standard chat, structured `action` field triggers the approve-gated queue.

## Dependencies
- No new dependencies installed
