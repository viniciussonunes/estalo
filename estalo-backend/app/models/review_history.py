"""
ReviewHistory — log imutável de cada avaliação feita pelo usuário.

Nunca é atualizado, só inserido. Permite ver a evolução de um card ao longo
do tempo: quando acertou, quando errou, como o intervalo foi crescendo.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReviewHistory(Base):
    __tablename__ = "review_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), nullable=False)

    # O que o usuário avaliou
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-4
    quality: Mapped[int] = mapped_column(Integer, nullable=False)       # 0-5 (SM-2)

    # Estado ANTES da avaliação (para reconstruir a linha do tempo)
    reps_antes: Mapped[int] = mapped_column(Integer, nullable=False)
    intervalo_antes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Estado DEPOIS da avaliação
    reps_depois: Mapped[int] = mapped_column(Integer, nullable=False)
    intervalo_depois: Mapped[int] = mapped_column(Integer, nullable=False)
    ease_factor_depois: Mapped[float] = mapped_column(Float, nullable=False)
    nova_due_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Classificação resultante para leitura rápida
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # novo|validando|dominado|critico

    # Idempotência: UUID gerado pelo cliente (X-Request-ID). Nullable para
    # compatibilidade com entradas antigas que não tinham o header.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    avaliado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
