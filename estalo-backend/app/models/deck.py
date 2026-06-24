"""
Deck — um conjunto de cards (o "set" do Quizlet).

Um deck mora dentro de uma pasta (ou solto, ligado direto ao usuário).
Ex: dentro de "Autenticação" você tem o deck "Métodos de MFA".
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Deck pode estar dentro de uma pasta OU solto (folder_id = None).
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="decks")
    folder: Mapped["Folder | None"] = relationship(back_populates="decks")
    cards: Mapped[list["Card"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan"
    )
