from datetime import datetime
from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CreateCaseRequest(BaseModel):
    case_name: str = Field(..., min_length=1, max_length=100)
    court_case_no: Optional[str] = None
    custody_type: str = Field(..., pattern="^(joint|sole|split)$")
    custody_ratio: Optional[dict[str, Any]] = None
    timezone: Optional[str] = "Asia/Taipei"


class UpdateCaseRequest(BaseModel):
    case_name: Optional[str] = Field(None, min_length=1, max_length=100)
    court_case_no: Optional[str] = None
    custody_ratio: Optional[dict[str, Any]] = None


class CaseMemberInfo(BaseModel):
    relation: str
    display_name: str
    joined_at: datetime


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_name: str
    court_case_no: Optional[str] = None
    custody_type: str
    custody_ratio: Optional[dict[str, Any]] = None
    timezone: str
    my_relation: str = ""  # set by handler after model_validate
    created_at: datetime


class CaseListItem(BaseModel):
    id: UUID
    case_name: str
    custody_type: str
    my_relation: str
    member_count: int
    child_count: int
    created_at: datetime


class CaseDetailResponse(CaseResponse):
    members: list[CaseMemberInfo] = []
    children: list[Any] = []
