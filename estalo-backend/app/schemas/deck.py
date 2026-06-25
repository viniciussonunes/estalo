from datetime import datetime
from pydantic import BaseModel


class DeckCreate(BaseModel):
    title: str
    description: str | None = None
    folder_id: int | None = None


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
    total_cards: int = 0
    memorization_pct: float = 0.0   # 0–100; fases: 0=Novo, 50=Validando, 100=Dominado

    model_config = {"from_attributes": True}
