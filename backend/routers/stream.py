"""WS /ws/ticks -- streams new ticks only, going forward. A client wanting
the backlog calls GET /state first; keeping "catch me up" (REST) and
"keep me updated" (WebSocket) separate is simpler than making the socket
do both.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/ticks")
async def ticks(websocket: WebSocket):
    service = websocket.app.state.service
    await websocket.accept()
    service._clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # this endpoint is send-only; just used to detect disconnect
    except WebSocketDisconnect:
        pass
    finally:
        service._clients.discard(websocket)
