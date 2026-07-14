from datetime import datetime
from pydantic import BaseModel, Field


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


class CardTutorRequest(BaseModel):
    """Corpo de POST /cards/{id}/tutor -- só relevante quando
    action=analyze (ver routers/cards.py); ausente/vazio é o normal
    quando action=explain, por isso user_attempt é opcional aqui e a
    obrigatoriedade é validada no router, não no schema (não dá pra
    expressar "obrigatório só se X" direto via Field)."""
    user_attempt: str | None = Field(None, min_length=1)


class CardTutorResponse(BaseModel):
    """Resposta de POST /cards/{id}/tutor (routers/cards.py) -- serve as
    duas ações do mesmo endpoint:

    - action=explain (botão "Explicar", ver PERSONA_EXPLICACAO_BREVE em
      tutor_service.py): só `explanation` vem preenchido, sempre curta
      (≤3 frases), sem cache.
    - action=analyze (Mentoria Ativa -- botão "Errei", ver
      tutor_service.analisar_feedback): os três campos vêm preenchidos,
      `explanation` carrega a explicação já no tom ajustado ao assunto.

    Não confundir com TutorResponse (schemas/study.py), usado pelo Tutor
    Inteligente completo em POST /study/cards/{id}/tutor -- é um endpoint
    e um propósito de UX diferentes (modal completo vs inline curto)."""
    explanation: str
    tipo_erro: str | None = None       # só populado quando action=analyze
    gap_cognitivo: str | None = None   # idem
