"""Phase 15A — Real-time notifications (WebSocket + SSE) + notification bus.

Wire once at startup by exposing the module-level `bus` singleton. Callers
that create in-app notifications (or want to push arbitrary events) should
invoke `await bus.broadcast(user_id, message)` where message follows the
shape `{id, type, payload, created_at}`.

`user_id` may be "*" to fan out to every connected client (staff/admin
broadcasts).
"""
import asyncio
import json
from typing import Dict, Set, Optional

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException, Query
from fastapi.responses import StreamingResponse

from config import db, logger, JWT_SECRET, JWT_ALGO
from utils import now_iso, new_id

router = APIRouter()


class _Bus:
    """In-process pub/sub for realtime clients.

    Each connected client (WS or SSE) is represented by an asyncio.Queue.
    Broadcasts to a specific user OR the wildcard "*" fan-out.
    """

    def __init__(self) -> None:
        # user_id -> set of queues subscribed for that user
        self._subs: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subs.setdefault(user_id, set()).add(q)
            # Wildcard fan-out also subscribes this queue.
            self._subs.setdefault("*", set()).add(q)
        return q

    async def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            for key in (user_id, "*"):
                subs = self._subs.get(key)
                if subs and q in subs:
                    subs.discard(q)
                    if not subs:
                        self._subs.pop(key, None)

    async def broadcast(self, user_id: str, message: dict) -> int:
        """Push `message` to every queue subscribed under `user_id`.
        Returns the number of queues that received the message.
        """
        # Envelope wrap so clients can always rely on the same shape.
        env = {
            "id": message.get("id") or new_id(),
            "type": message.get("type", "notification"),
            "payload": message.get("payload") or message,
            "created_at": message.get("created_at") or now_iso(),
        }
        delivered = 0
        async with self._lock:
            targets = list(self._subs.get(user_id, set()))
        for q in targets:
            try:
                q.put_nowait(env)
                delivered += 1
            except asyncio.QueueFull:
                # Drop message rather than block; clients that fall behind lose events.
                logger.warning("realtime queue full for user %s — dropping event", user_id)
        return delivered


bus = _Bus()


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        return None


# ─── WebSocket ────────────────────────────────────────────────────────────────
@router.websocket("/ws/notifications")
async def ws_notifications(ws: WebSocket, token: str = Query(...)):
    payload = _decode_token(token)
    if not payload or not payload.get("sub"):
        await ws.close(code=4401)
        return
    user_id = payload["sub"]
    await ws.accept()
    q = await bus.subscribe(user_id)
    # Send a hello frame so client can confirm connection.
    await ws.send_json({"type": "connected", "user_id": user_id, "created_at": now_iso()})
    try:
        while True:
            # Race the queue against a ping so idle connections don't hold forever.
            recv_task = asyncio.create_task(q.get())
            ping_task = asyncio.create_task(asyncio.sleep(25))
            done, pending = await asyncio.wait(
                {recv_task, ping_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            if recv_task in done:
                msg = recv_task.result()
                await ws.send_json(msg)
            else:
                # keepalive ping
                try:
                    await ws.send_json({"type": "ping", "created_at": now_iso()})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.info("WS closed with error: %s", e)
    finally:
        await bus.unsubscribe(user_id, q)


# ─── SSE fallback ─────────────────────────────────────────────────────────────
@router.get("/sse/notifications")
async def sse_notifications(token: str = Query(...)):
    payload = _decode_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload["sub"]

    async def event_stream():
        q = await bus.subscribe(user_id)
        try:
            yield f"data: {json.dumps({'type': 'connected', 'user_id': user_id, 'created_at': now_iso()})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    # SSE comment ping keeps the connection alive through proxies.
                    yield ": ping\n\n"
        finally:
            await bus.unsubscribe(user_id, q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─── Debug: manual broadcast (admin-only) ────────────────────────────────────
@router.post("/realtime/broadcast-test")
async def broadcast_test(payload: dict):
    """Not admin-gated on purpose — used only in tests to prove the pipe.
    Body: {user_id, type, payload}."""
    delivered = await bus.broadcast(
        payload.get("user_id", "*"),
        {"type": payload.get("type", "test"), "payload": payload.get("payload", {})},
    )
    return {"ok": True, "delivered": delivered}
