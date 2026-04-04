"""Chat router: session CRUD + SSE message endpoint."""

import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.chat import chat_service
from app.schemas import ChatMessageRequest, ChatSessionOut

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
def create_session():
    """Create a new chat session."""
    session = chat_service.create_session()
    return ChatSessionOut(
        session_id=session.session_id,
        created_at=session.created_at,
        expires_at=session.expires_at,
        agent_states=session.agent_states,
        last_plan=session.last_plan,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionOut)
def get_session(session_id: str):
    """Retrieve an existing chat session, including last known agent states and plan."""
    session = chat_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return ChatSessionOut(
        session_id=session.session_id,
        created_at=session.created_at,
        expires_at=session.expires_at,
        agent_states=session.agent_states,
        last_plan=session.last_plan,
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    """Delete (expire) a chat session."""
    found = chat_service.expire_session(session_id)
    if not found:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, payload: ChatMessageRequest):
    """Send a user message; returns an SSE stream of agent events."""
    session = chat_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    async def event_stream() -> AsyncGenerator[str, None]:
        async for event in chat_service.process_message(session_id, payload.message):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
