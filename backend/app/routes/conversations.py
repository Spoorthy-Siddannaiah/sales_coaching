from fastapi import APIRouter, HTTPException, Request

from app.repositories import conversations
from app.workflow_models import CustomerContext

router = APIRouter()


@router.get("/conversations")
def list_saved(request: Request):
    return conversations.list_conversations(request.app.state.settings.database_path)


@router.get("/conversations/{conversation_id}")
def retrieve(conversation_id: str, request: Request):
    record = conversations.detail(request.app.state.settings.database_path, conversation_id)
    if record is None:
        raise HTTPException(404, detail="Conversation not found.")
    return record


@router.put("/conversations/{conversation_id}/context")
def update_context(conversation_id: str, context: CustomerContext, request: Request):
    if not conversations.save_context(request.app.state.settings.database_path, conversation_id, context):
        raise HTTPException(404, detail="Conversation not found.")
    return context
