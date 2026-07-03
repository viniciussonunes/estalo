"""
Pasta — a sua dor #3 resolvida.

Aqui está o truque: uma pasta pode apontar pra outra pasta (o "pai").
Isso se chama árvore auto-referenciada. Com UMA tabela você consegue
infinitos níveis — a gente só limita em 4 por regra de negócio (config).

Exemplo da árvore:
    Certificações Microsoft   (nível 1, parent_id = None)
    └── SC-900                (nível 2)
        └── Identidade        (nível 3)
            └── Autenticação  (nível 4)  ← aqui dentro ficam os decks/cards
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Dono da pasta.
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # AQUI está a mágica: a pasta aponta pra outra pasta da MESMA tabela.
    # parent_id = None significa que é uma pasta raiz (nível 1).
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id"), nullable=True
    )

    # depth guarda o nível (1 a 4). A gente preenche e valida no service.
    depth: Mapped[int] = mapped_column(Integer, default=1)

    # Cor de identificação visual (hex ou var(--token) do frontend). None =
    # usa a cor padrão do tema, sem personalização.
    color: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    owner: Mapped["User"] = relationship(back_populates="folders")

    # Filhos: as subpastas dentro desta pasta.
    children: Mapped[list["Folder"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    # Pai: a pasta que contém esta. remote_side diz ao SQLAlchemy qual lado
    # da auto-referência é o "pai".
    parent: Mapped["Folder | None"] = relationship(
        back_populates="children",
        remote_side=[id],
    )

    # Decks que ficam diretamente dentro desta pasta.
    decks: Mapped[list["Deck"]] = relationship(back_populates="folder")
