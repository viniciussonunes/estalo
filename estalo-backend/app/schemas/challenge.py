"""
Schemas do módulo Challenge (tabela paralela a cards, ver
app/models/challenge.py). Nasceu como protótipo genérico e hoje hospeda
também o Mentor de Inglês Ativo (type default "ENGLISH_TUTOR") -- ver
challenge_service.py pro prompt específico desse tipo.

`content` fica tipado como dict[str, Any] -- o shape interno varia por
`type` (pra ENGLISH_TUTOR é {student_attempt, native_correction, why,
collocations}; outros tipos têm shapes próprios) e não é fixo, então não
faz sentido travar campos aqui.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChallengeBase(BaseModel):
    deck_id: int
    type: str
    content: dict[str, Any]
    explanation: str | None = None
    tutor_explanation: str | None = None
    language_level: str | None = None


class ChallengeCreate(ChallengeBase):
    """O que o cliente manda pra criar um challenge."""


class ChallengeResponse(ChallengeBase):
    """O que a API devolve sobre um challenge.

    id/created_at ficam None quando o objeto é um PREVIEW
    (POST /challenges/generate com preview_only=True) -- a IA gerou e o
    schema validou, mas nada foi persistido. Em qualquer challenge de
    verdade (POST /challenges, POST /generate sem preview_only, ou GET)
    os dois vêm sempre preenchidos.
    """
    id: int | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Geração por IA (POST /challenges/generate, ver challenge_service.py) ---

class ChallengeGenerateRequest(BaseModel):
    deck_id: int
    # min_length baixo de propósito -- uma tentativa de inglês válida pode
    # ser bem curta (ex: "He don't know", 13 chars). Não é texto de estudo
    # longo como no tipo genérico original.
    raw_content: str = Field(..., min_length=3)
    # ENGLISH_TUTOR é o default -- o Mentor de Inglês Ativo é o caso de uso
    # principal deste módulo hoje; outros tipos (FILL_THE_GAP, etc.)
    # continuam funcionando via API, só não são mais o padrão.
    type: str = Field("ENGLISH_TUTOR", min_length=1)
    depth: str = Field("medium", pattern="^(summary|medium|deep)$")
    # CEFR -- efetivamente usado pelo prompt só quando type=ENGLISH_TUTOR
    # (ver challenge_service._montar_prompt_mentor_ingles), mas fica no
    # schema geral pra não acoplar validação ao valor de `type`.
    language_level: str = Field("B1", pattern="^(A1|A2|B1|B2|C1|C2)$")
    # Ver challenge_service.gerar_challenge: True pula db.add()/db.commit(),
    # devolvendo o Challenge gerado (id/created_at = None) sem gravar nada.
    preview_only: bool = False


class ChallengeAIPayload(BaseModel):
    """Formato EXATO que a IA deve devolver -- só o que ela de fato gera.

    deck_id/type/language_level nunca vêm da IA (já são conhecidos, vêm do
    pedido do usuário) -- só content/explanation/tutor_explanation. Usado
    pra validar (e, se inválido, disparar a tentativa de correção em
    challenge_service.gerar_challenge) a resposta bruta da IA antes dela
    virar um Challenge de verdade no banco.
    """
    content: dict[str, Any] = Field(..., min_length=1)
    explanation: str = Field(..., min_length=1)
    tutor_explanation: str = Field(..., min_length=1)
