"""Pydantic 数据模型"""
from pydantic import BaseModel, Field
from typing import Optional

from server.personal.models import PlanRef


class ChatRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[\w-]+$")
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=32, pattern=r"^[\w-]+$")
    message: str = Field(min_length=1, max_length=16000)
    request_id: Optional[str] = Field(default=None, min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    plan_ref: PlanRef | None = None


class PreferenceUpdate(BaseModel):
    pref_type: str
    value: str
    action: str = Field(default="append", pattern=r"^(append|replace)$")


class SessionRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[\w-]+$")
