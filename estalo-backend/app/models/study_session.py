"""
StudySession — resumo de uma rodada de estudo já encerrada (Modo Aprender).

Diferente de ReviewHistory (1 linha por resposta de card), aqui é 1 linha
por RODADA inteira. É só um rollup para o gráfico de evolução do Dashboard;
não substitui nem se relaciona com ReviewHistory — cada resposta individual
continua sendo logada lá, como sempre.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StudySession(Base):
    __tablename__ = "study_sessions"
    # GET /study/history filtra por user_id e ordena por finished_at desc —
    # mesmo padrão de índice composto já usado em ReviewHistory.
    __table_args__ = (
        Index("ix_study_sessions_user_finished", "user_id", "finished_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    finished_at:      Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    total_cards:      Mapped[int]      = mapped_column(Integer, nullable=False)
    acertos_primeira: Mapped[int]      = mapped_column(Integer, nullable=False)
    duracao_seg:      Mapped[int]      = mapped_column(Integer, nullable=False)
    modo:             Mapped[str]      = mapped_column(String(16), nullable=False)  # "deck" | "global"
