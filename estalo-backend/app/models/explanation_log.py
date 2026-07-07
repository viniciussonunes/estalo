"""
ExplanationLog — log imutável de cada transição de ExplanationCache: a
criação da v1 e cada refinamento subsequente por feedback negativo. Nunca
é atualizado, só inserido — mesmo papel que ReviewHistory tem pro Review
(ver review_history.py). Existe só pra auditoria/debug ("por que essa
explicação chegou nesse nível"), não é consultado no fluxo normal do
Modo Aprender.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _agora_utc() -> datetime:
    """Equivalente não-deprecated de datetime.utcnow() que preserva
    naive-UTC (mesmo padrão adotado em app/routers/study.py e afins) --
    datetime.now(timezone.utc) sozinho devolveria um datetime AWARE, e
    esta coluna (como todas no projeto) é DateTime naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ExplanationLog(Base):
    __tablename__ = "explanation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    explanation_cache_id: Mapped[int] = mapped_column(
        ForeignKey("explanation_cache.id"), nullable=False, index=True
    )

    versao: Mapped[int] = mapped_column(Integer, nullable=False)
    texto_explicacao: Mapped[str] = mapped_column(Text, nullable=False)
    # Motivo que originou ESTA versão — nulo na v1 (criação), preenchido
    # em cada refinamento seguinte (o 👎 que motivou a mudança).
    motivo_rejeicao: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=_agora_utc)
