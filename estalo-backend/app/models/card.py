"""
Card — a unidade de estudo: frente (pergunta) e verso (resposta).

Repara que o card NÃO guarda o progresso do estudo. Isso fica na tabela
Review, separada. Explico o porquê lá no review.py.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    front: Mapped[str] = mapped_column(Text, nullable=False)  # pergunta
    back: Mapped[str] = mapped_column(Text, nullable=False)   # resposta

    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id"), nullable=False)

    # Marca se o card foi gerado por IA (sua dor #1) ou digitado à mão.
    # Útil pra você medir depois quanto a IA te poupou de trabalho.
    source: Mapped[str] = mapped_column(String, default="manual")  # "manual" | "ai"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    deck: Mapped["Deck"] = relationship(back_populates="cards")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
