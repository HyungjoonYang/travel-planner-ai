"""Chat router: session CRUD + SSE message endpoint."""

import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.chat import chat_service
from app.database import get_db
from app.models import ChatMessage
from app.schemas import ChatMessageRequest, ChatSessionOut

router = APIRouter(prefix="/chat", tags=["chat"])

_GET_SESSION_HISTORY_LIMIT = 10


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
        message_history=session.message_history,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionOut)
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Retrieve an existing chat session, including last known agent states and plan.

    message_history is populated from the DB (last 10 messages), falling back to
    the in-memory history when no DB records exist.
    """
    session = chat_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # Prefer DB records for message_history so reconnecting clients see persisted bubbles.
    message_history = session.message_history
    try:
        db_msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(_GET_SESSION_HISTORY_LIMIT)
            .all()
        )
        if db_msgs:
            message_history = [
                {
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in reversed(db_msgs)
            ]
    except Exception:
        pass  # fall back to in-memory

    return ChatSessionOut(
        session_id=session.session_id,
        created_at=session.created_at,
        expires_at=session.expires_at,
        agent_states=session.agent_states,
        last_plan=session.last_plan,
        message_history=message_history,
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    """Delete (expire) a chat session."""
    found = chat_service.expire_session(session_id)
    if not found:
        raise HTTPException(status_code=404, detail="Session not found")


@router.delete("/sessions/{session_id}/messages", status_code=204)
def clear_session_messages(session_id: str, db: Session = Depends(get_db)):
    """Clear conversation history for a session (DB + in-memory)."""
    session = chat_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # Delete DB records
    try:
        db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        db.commit()
    except Exception:
        db.rollback()

    # Clear in-memory history
    chat_service.reset_conversation(session_id)


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
):
    """Send a user message; returns an SSE stream of agent events."""
    session = chat_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    async def event_stream() -> AsyncGenerator[str, None]:
        async for event in chat_service.process_message(session_id, payload.message, db=db):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
