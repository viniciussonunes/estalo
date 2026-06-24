"""
Schemas de deck — o conjunto de cards (o "set" do Quizlet).
"""
from datetime import datetime

from pydantic import BaseModel


class DeckCreate(BaseModel):
    title: str
    description: str | None = None
    folder_id: int | None = None  # pode morar numa pasta ou ficar solto


class DeckUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    folder_id: int | None = None


class DeckOut(BaseModel):
    id: int
    title: str
    description: str | None
    folder_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
