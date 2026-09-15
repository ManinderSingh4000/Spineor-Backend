from pydantic import BaseModel
from typing import Optional, List


class Button(BaseModel):
    id: str
    label: str


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    action_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    buttons: List[Button]
    input_enabled: bool
