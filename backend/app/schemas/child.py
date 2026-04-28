from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CreateChildRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)
    birth_date: date
    notes: Optional[str] = Field(None, max_length=200)


class UpdateChildRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=50)
    notes: Optional[str] = Field(None, max_length=200)


class ChildResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    display_name: str
    birth_date: date
    age_years: int
    notes: Optional[str]
    created_at: datetime
