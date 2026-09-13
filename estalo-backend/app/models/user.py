"""
Usuário — quem usa o Estalo.

Como o app é multi-usuário desde o começo, TUDO no banco aponta de volta
pra um usuário. Ninguém vê os cards de ninguém.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Freio de força bruta no login (ver services/login_throttle.py).
    # Erros CONSECUTIVOS: um login certo zera. locked_until é naive-UTC,
    # como toda coluna DateTime do projeto.
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Geração dos crachás válidos. Todo token carrega a versão em que foi
    # emitido; trocar a senha incrementa isto e, com isso, todo token
    # antigo deixa de valer -- é o único jeito de derrubar uma sessão
    # aberta em outro aparelho, já que JWT é assinado e não consultado.
    # Começa em 1 pra que token ANTIGO (sem o campo `ver`) continue
    # valendo: ausente é lido como 1. Ver security.py e dependencies.py.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Um usuário tem várias pastas, decks e reviews.
    folders: Mapped[list["Folder"]] = relationship(back_populates="owner")
    decks: Mapped[list["Deck"]] = relationship(back_populates="owner")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")
