"""
UserQuota — controla quantos tokens de IA (Gemini) cada usuário consumiu
no dia, pra uma conta sozinha não estourar a cota compartilhada da chave.

Motivo concreto (não teórico): a chave já ficou sem cota nesta mesma sessão
por causa de testes em rajada, retornando 429 pra usuários reais tentando
usar o Tutor Inteligente. Isso barra ANTES de gastar cota numa chamada que
o usuário nem vai conseguir aproveitar.

1 linha por usuário — user_id é a própria chave primária (não existe caso
de uso pra mais de uma linha de cota por usuário).
"""
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Usado tanto no default da coluna quanto por quem lê a cota de um usuário
# que ainda não tem linha em user_quotas (ex: GET /admin/users) -- os dois
# lugares precisam concordar no mesmo número, daí a constante em vez de
# repetir o literal.
DEFAULT_DAILY_LIMIT = 50_000


class UserQuota(Base):
    __tablename__ = "user_quotas"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    daily_tokens_consumed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_DAILY_LIMIT)
    last_reset_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
