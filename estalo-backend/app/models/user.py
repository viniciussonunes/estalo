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

    # Um usuário tem várias pastas, decks e reviews.
    folders: Mapped[list["Folder"]] = relationship(back_populates="owner")
    decks: Mapped[list["Deck"]] = relationship(back_populates="owner")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")
