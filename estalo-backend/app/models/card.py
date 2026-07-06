import hashlib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base


def calcular_content_hash(front: str, back: str) -> str:
    """SHA-256 de front+back normalizados (trim + lowercase), com separador
    explícito (\\x1f) pra não colidir o hash de ("ab", "c") com ("a", "bc").

    Usado tanto no backfill de cards existentes (main.py:_migrar()) quanto
    na futura detecção de duplicatas do Motor de Importação Anki — as duas
    pontas precisam calcular exatamente do mesmo jeito, ou a comparação
    nunca bate.
    """
    normalizado = f"{front.strip().lower()}\x1f{back.strip().lower()}"
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()


class Card(Base):
    __tablename__ = "cards"
    # Não-único de propósito: o mesmo front/back pode legitimamente existir
    # em dois decks diferentes (ou até no mesmo deck, por decisão do
    # usuário) — uma constraint UNIQUE bloquearia isso e, pior, uma UNIQUE
    # global quebraria a migração inteira se qualquer duplicata já existir
    # na base de produção hoje. A garantia de "não duplicar ao importar"
    # fica na lógica de import (checar antes de inserir), não numa
    # constraint de banco — este índice só existe pra essa checagem ser
    # rápida (O(log n) em vez de varrer o deck inteiro).
    __table_args__ = (
        Index("ix_cards_deck_content_hash", "deck_id", "content_hash"),
    )

    id:      Mapped[int] = mapped_column(Integer, primary_key=True)
    front:   Mapped[str] = mapped_column(Text, nullable=False)
    back:    Mapped[str] = mapped_column(Text, nullable=False)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id"), nullable=False, index=True)
    source:  Mapped[str] = mapped_column(String, default="manual")  # "manual" | "ai"

    # Dados pré-gerados para o Modo Aprender (gerados no nascimento, carregamento instantâneo)
    options:     Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    explanation: Mapped[str | None]  = mapped_column(Text, nullable=True, default=None)

    # Hash de conteúdo (ver calcular_content_hash acima), pra deduplicação
    # do Motor de Importação Anki. Nullable porque cards de antes desta
    # coluna só ganham isso via backfill da migração (main.py:_migrar()).
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Explicação do Tutor Inteligente (ver app/services/tutor_service.py),
    # cacheada no card na primeira vez que é gerada — a mesma pergunta não
    # volta a chamar o Gemini nas próximas vezes que o usuário errar/pedir
    # ajuda neste card.
    tutor_explanation: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    deck:    Mapped["Deck"]         = relationship(back_populates="cards")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    review_history: Mapped[list["ReviewHistory"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    explanation_cache: Mapped[list["ExplanationCache"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
