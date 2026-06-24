"""
Schemas de estudo.

StudyCard: o card que a API entrega pra você revisar (frente, verso e info
de quando ele vence).
ReviewAnswer: a nota que você dá depois de ver a resposta (0 a 5).
StudyStats: um resumo de quantos cards estão vencidos / em dia.
"""
from datetime import datetime

from pydantic import BaseModel, Field


class StudyCard(BaseModel):
    card_id: int
    front: str
    back: str
    due_date: datetime
    repetitions: int

    model_config = {"from_attributes": True}


class ReviewAnswer(BaseModel):
    # quality 0-5: 0-2 errou, 3 acertou difícil, 4 acertou, 5 acertou fácil
    quality: int = Field(ge=0, le=5)


class ReviewResult(BaseModel):
    """O que volta depois de responder: o novo estado do SM-2."""
    card_id: int
    interval: int
    ease_factor: float
    repetitions: int
    next_due: datetime


class StudyStats(BaseModel):
    total_cards: int
    due_now: int      # vencidos, prontos pra revisar
    new_cards: int    # nunca estudados
