from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["viewer", "editor", "admin"]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = ""


class WorkspaceOut(BaseModel):
    id: int
    name: str
    description: str
    role: str


class MemberIn(BaseModel):
    email: EmailStr
    role: Role


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    owner_id: int
    title: str
    filename: str
    category: str
    summary: str
    tags: list[str]
    routing_reason: str
    visibility: str
    current_version: int
    created_at: datetime
    updated_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    filename: str
    size: int
    uploaded_by: int
    created_at: datetime


class ACLEntry(BaseModel):
    user_id: int
    permission: Literal["read", "write"]


class ACLIn(BaseModel):
    visibility: Literal["workspace", "restricted"]
    entries: list[ACLEntry] = []


class QAIn(BaseModel):
    question: str = Field(min_length=3)
    workspace_id: int | None = None
    top_k: int = Field(default=5, ge=1, le=15)


class QAOut(BaseModel):
    answer: str
    sources: list[dict]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    workspace_id: int | None
    action: str
    resource_type: str
    resource_id: int | None
    details: dict
    ip: str
    created_at: datetime
