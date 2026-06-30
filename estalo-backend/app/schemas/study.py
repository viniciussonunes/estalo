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
    quality: int = Field(ge=0, le=5)


class ReviewResult(BaseModel):
    card_id: int
    interval: int
    ease_factor: float
    repetitions: int
    next_due: datetime


class StudyStats(BaseModel):
    total_cards: int
    novos: int          # repetitions == 0 (nunca estudados)
    validando: int      # repetitions == 1
    dominados: int      # repetitions >= 2
    criticos: int       # due_date < hoje AND repetitions > 0
    hoje: int           # due_date == hoje (data, sem hora) AND repetitions > 0
    # legado — mantidos para não quebrar clientes antigos
    due_now: int
    new_cards: int
    validating: int
    dominated: int


# --- Modo Aprender (múltipla escolha gerada por IA) ---

class QuizOption(BaseModel):
    letter: str
    text: str


class QuizQuestion(BaseModel):
    card_id: int
    question: str
    options: list[QuizOption]
    correct_letter: str
    explanation: str
    repetitions: int = 0    # fase atual do card (0=Novo, 1=Validando, ≥2=Dominado)


# --- Modo Revelar ---

class RevealCard(BaseModel):
    card_id: int
    front: str
    back: str
    explanation: str
