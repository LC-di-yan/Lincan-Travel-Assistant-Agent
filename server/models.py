"""Pydantic 数据模型"""
from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    user_id: str = "default_user"
    session_id: Optional[str] = None
    message: str


class PreferenceUpdate(BaseModel):
    pref_type: str
    value: str
    action: str = "append"  # append | replace


class SessionRequest(BaseModel):
    user_id: str = "default_user"
