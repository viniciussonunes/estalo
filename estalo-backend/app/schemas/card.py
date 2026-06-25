from datetime import datetime
from pydantic import BaseModel


class CardCreate(BaseModel):
    front: str
    back: str
    source: str = "manual"


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
    options: list[str] | None = None     # 3 distratores pré-gerados pela IA
    explanation: str | None = None        # explicação pré-gerada pela IA
    repetitions: int = 0                  # fase SM-2 atual do usuário (0=Novo,1=Validando,≥2=Dominado)

    model_config = {"from_attributes": True}
