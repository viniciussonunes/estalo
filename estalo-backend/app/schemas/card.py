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


class CardTutorResponse(BaseModel):
    """Resposta de POST /cards/{id}/tutor (botão "Explicar", ver
    routers/cards.py) -- sempre curta (≤3 frases, ver PERSONA_EXPLICACAO_BREVE
    em tutor_service.py), sem cache. Não confundir com TutorResponse
    (schemas/study.py), usado pelo Tutor Inteligente completo em
    POST /study/cards/{id}/tutor -- os dois têm o mesmo shape hoje, mas
    são schemas separados de propósito: um dia um pode ganhar campo que
    o outro não precisa."""
    explanation: str
