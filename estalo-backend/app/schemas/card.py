"""
Schemas de card — a unidade de estudo: frente e verso.
"""
from datetime import datetime

from pydantic import BaseModel


class CardCreate(BaseModel):
    front: str
    back: str
    source: str = "manual"  # "manual" ou "ai"


class CardUpdate(BaseModel):
    front: str | None = None
    back: str | None = None


class CardOut(BaseModel):
    id: int
    front: str
    back: str
    deck_id: int
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}
