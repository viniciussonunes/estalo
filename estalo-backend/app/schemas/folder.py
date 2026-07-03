"""
Schemas de pasta.

O FolderTree é especial: ele se referencia (uma pasta tem uma lista de
FolderTree dentro). Isso espelha a árvore do banco e deixa a API devolver
a hierarquia inteira de uma vez, prontinha pro frontend desenhar.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FolderCreate(BaseModel):
    """O que o usuário manda pra criar uma pasta."""
    name: str
    parent_id: int | None = None  # None = pasta raiz (nível 1)
    color: str | None = None      # hex ou var(--token) do frontend; None = cor padrão


class FolderUpdate(BaseModel):
    """Renomear e/ou trocar a cor — os dois campos são opcionais, só o que
    vier preenchido é atualizado (mesmo padrão do DeckUpdate)."""
    name: str | None = None
    color: str | None = None


class FolderOut(BaseModel):
    """Uma pasta isolada, sem os filhos."""
    id: int
    name: str
    parent_id: int | None
    depth: int
    color: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FolderTree(BaseModel):
    """Uma pasta COM seus filhos aninhados — a árvore inteira."""
    id: int
    name: str
    depth: int
    color: str | None = None
    children: list[FolderTree] = []

    model_config = {"from_attributes": True}


# Necessário porque FolderTree se referencia (auto-referência).
FolderTree.model_rebuild()
