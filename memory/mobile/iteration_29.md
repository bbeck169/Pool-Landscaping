# Iteration 29 — Wave M3: F2d + F2e + F2f

## What was implemented

### F2d — Chat Attachments (chat.tsx)
- Paperclip button in composer row (uses ActionSheetIOS on iOS, Alert on Android)
- Three picker options: Take Photo, Choose from Library, Choose File
- Uploads directly to `POST /api/chat/attachments/upload` via FormData + XHR
- `pending[]` state array holds uploaded attachment objects
- Pending attachment chips displayed above composer with remove (×) button
- Send button includes `attachment_ids` in message body when pending exists
- Inline attachment links (`📎 name`) rendered under each message with attachments
- Loading spinner on paperclip while uploading
- Send disabled when uploading or (no text AND no pending)

### F2e — Persona Avatar Upload (ai-employees.tsx)
- Camera icon overlay (22px circle) on each persona avatar
- Bottom-sheet Modal opened on camera press
- Modal contains: current avatar preview, persona name, FileUpload component
- FileUpload configured: purpose="persona_avatar", linkedEntityType="persona", accept images only
- On upload success: PATCH `/api/ai-employees/{eid}` with `avatar_url: /api/files/{id}/download`
- "Reset to default" button: PATCHes with `/avatars/personas/{key}.jpg`
- Optimistic list update on success
- AuthedImage for personas with custom avatar_url

### F2f — Staff Profile Photo (new profile.tsx)
- New screen at `/app/mobile/app/(app)/profile.tsx`
- Fetches `/api/auth/me` on mount, falls back to auth context user
- InitialBadge component (first letter of name) when no photo
- AuthedImage when `profile_photo_url` is set (extracts fileId from URL pattern)
- FileUpload: purpose="staff_profile_photo", linkedEntityType="user", accept images
- On upload: PATCH `/api/users/me` with `profile_photo_url: /api/files/{id}/download`
- "Remove photo" button (only visible when photo exists): PATCHes `profile_photo_url: null`
- Identity card section: Name, Email, Role
- Profile card in more.tsx converted from View to Pressable with chevron → navigates to profile

## Web-to-Mobile Mapping

| Web Component | Mobile Screen | API Endpoints |
|---|---|---|
| TeamChatPage.jsx | app/(app)/chat.tsx | POST /api/chat/attachments/upload, POST /api/chat/conversations/{id}/messages |
| PersonaAvatarUploadModal.jsx + AiPersonasScopePage.jsx | app/ai-employees.tsx | PATCH /api/ai-employees/{eid} |
| MyProfilePage.jsx | app/(app)/profile.tsx | GET /api/auth/me, PATCH /api/users/me |

## Dependencies installed
None new — all required packages (expo-image-picker, expo-document-picker, expo-image) were already available from Wave M1/M2.

## Known Issues
- None. All features render and compile correctly.
- Tunnel preview was unavailable during testing (infrastructure), but localhost:3001 confirmed all screens render.

## Test Results
- 77/77 tests passing (59 existing + 18 new)
- New test files: f2d-chat-attachments.test.tsx (5), f2e-persona-avatar.test.tsx (6), f2f-staff-profile.test.tsx (7)
