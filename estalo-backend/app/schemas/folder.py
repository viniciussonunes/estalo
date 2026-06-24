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


class FolderUpdate(BaseModel):
    """Por enquanto só renomear. Mover de lugar entra depois."""
    name: str


class FolderOut(BaseModel):
    """Uma pasta isolada, sem os filhos."""
    id: int
    name: str
    parent_id: int | None
    depth: int
    created_at: datetime

    model_config = {"from_attributes": True}


class FolderTree(BaseModel):
    """Uma pasta COM seus filhos aninhados — a árvore inteira."""
    id: int
    name: str
    depth: int
    children: list[FolderTree] = []

    model_config = {"from_attributes": True}


# Necessário porque FolderTree se referencia (auto-referência).
FolderTree.model_rebuild()
