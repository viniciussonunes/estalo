from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base


class Card(Base):
    __tablename__ = "cards"

    id:      Mapped[int] = mapped_column(Integer, primary_key=True)
    front:   Mapped[str] = mapped_column(Text, nullable=False)
    back:    Mapped[str] = mapped_column(Text, nullable=False)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id"), nullable=False)
    source:  Mapped[str] = mapped_column(String, default="manual")  # "manual" | "ai"

    # Dados pré-gerados para o Modo Aprender (gerados no nascimento, carregamento instantâneo)
    options:     Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    explanation: Mapped[str | None]  = mapped_column(Text, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    deck:    Mapped["Deck"]         = relationship(back_populates="cards")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    review_history: Mapped[list["ReviewHistory"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
