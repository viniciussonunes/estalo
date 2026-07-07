"""
ExplanationCache — estado atual (mutável) da explicação de erro pra cada
par (card, alternativa errada escolhida). Mesmo papel que Review tem pro
SM-2: uma linha por par, que evolui in-place via `versao` a cada
refinamento por feedback negativo. ExplanationLog (explanation_log.py)
faz o papel de ReviewHistory — log imutável de cada transição, só pra
auditoria/debug, nunca lido no caminho quente do Modo Aprender.
"""
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ExplanationCache(Base):
    __tablename__ = "explanation_cache"
    # Único de propósito — diferente do content_hash de Card (não-único,
    # duplicata é legítima ali). Aqui só existe UMA explicação canônica
    # por par card+alternativa-errada; ela evolui in-place via `versao`,
    # nunca se acumula em várias linhas pro mesmo par.
    __table_args__ = (
        Index("ix_explanation_cache_card_alt", "card_id", "alternativa_escolhida", unique=True),
    )

    id:      Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), nullable=False)
    alternativa_escolhida: Mapped[str] = mapped_column(String(500), nullable=False)

    texto_explicacao_atual: Mapped[str] = mapped_column(Text, nullable=False)
    # Nulo até o primeiro 👎 — a v1 nasce sem motivo de rejeição.
    motivo_rejeicao_mais_recente: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    versao: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    card: Mapped["Card"] = relationship(back_populates="explanation_cache")
    # cascade="all, delete-orphan" -- sem isso, apagar um card (e por
    # cascata, seu ExplanationCache) quebra em produção (Postgres) com
    # ForeignKeyViolation: explanation_log ainda referencia a linha que o
    # SQLAlchemy tentou apagar. SQLite (dev/testes) não enforça FK por
    # padrão, então esse bug só aparecia contra o banco real -- achado
    # testando exclusão de deck de ponta a ponta em produção.
    logs: Mapped[list["ExplanationLog"]] = relationship(
        back_populates="cache", cascade="all, delete-orphan"
    )
