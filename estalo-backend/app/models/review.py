"""
Review — o motor da repetição espaçada (sua dor #2).

Por que uma tabela separada do Card? Porque o progresso é de CADA usuário.
Se amanhã você compartilhar um deck com um amigo, vocês dois estudam os
MESMOS cards, mas cada um tem o SEU próprio ritmo de revisão. O card é
compartilhado; o progresso é pessoal. Separar agora evita reescrever tudo depois.

Os 4 campos que o algoritmo SM-2 usa:
- ease_factor: quão "fácil" o card é pra você (começa em 2.5). Quanto maior, mais espaçado.
- interval: quantos dias até a próxima revisão.
- repetitions: quantas vezes seguidas você acertou.
- due_date: a data em que o card "vence" e volta a aparecer.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Review(Base):
    __tablename__ = "reviews"
    # Garante UM review por par (usuário, card). Não dá pra duplicar.
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_user_card"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), nullable=False)

    # --- Estado do SM-2 ---
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_reviewed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="reviews")
    card: Mapped["Card"] = relationship(back_populates="reviews")
