"""
StudySession — resumo de uma rodada de estudo já encerrada (Modo Aprender).

Diferente de ReviewHistory (1 linha por resposta de card), aqui é 1 linha
por RODADA inteira. Não substitui nem se relaciona com ReviewHistory —
cada resposta individual continua sendo logada lá, como sempre.

Continua sendo gravado a cada sessão (POST /study/session/log, ver
Aprender.jsx) mesmo sem nenhum consumidor de leitura hoje — o gráfico de
evolução do Dashboard que lia isso (GET /study/history) foi removido, mas
o rollup em si segue sendo persistido caso uma futura visualização volte
a precisar dele.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StudySession(Base):
    __tablename__ = "study_sessions"
    # Sem consumidor de leitura hoje (ver docstring acima), mas mantido —
    # mesmo padrão de índice composto já usado em ReviewHistory, pronto pra
    # já servir uma futura consulta por user_id + finished_at sem precisar
    # de nova migração.
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
