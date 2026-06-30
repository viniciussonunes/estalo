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
    quality: int | None = Field(None, ge=0, le=5, description="Escala SM-2 legada (0-5)")
    difficulty: int | None = Field(None, ge=1, le=4, description="Escala amigável: 1=Esqueci 2=Difícil 3=Bom 4=Fácil")

    def quality_efetivo(self) -> int:
        """Resolve quality a partir de difficulty se quality não vier."""
        if self.quality is not None:
            return self.quality
        if self.difficulty is not None:
            return {1: 1, 2: 3, 3: 4, 4: 5}[self.difficulty]
        raise ValueError("Informe quality (0-5) ou difficulty (1-4)")


class ReviewResult(BaseModel):
    card_id: int
    interval: int
    ease_factor: float
    repetitions: int
    next_due: datetime
    status: str                 # novo | validando | dominado | critico
    difficulty_usada: int       # 1-4, para o frontend mostrar feedback


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


class HistoryEntry(BaseModel):
    id: int
    card_id: int
    difficulty: int
    quality: int
    reps_antes: int
    reps_depois: int
    intervalo_depois: int
    status: str
    avaliado_em: datetime
    model_config = {"from_attributes": True}


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
