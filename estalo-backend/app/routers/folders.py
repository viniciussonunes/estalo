"""
CRUD de pastas — a árvore de 4 níveis virando endpoint.

Toda operação aqui é protegida (precisa de crachá) e isolada por usuário:
você só enxerga e mexe nas SUAS pastas. Se tentar acessar a pasta de outro,
a API responde "não encontrada" (404) — nem revela que existe.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.dependencies import get_current_user_id
from app.models import Folder
from app.schemas.folder import FolderCreate, FolderOut, FolderTree, FolderUpdate

router = APIRouter(prefix="/folders", tags=["Pastas"])


def _buscar_pasta_do_usuario(folder_id: int, user_id: int, db: Session) -> Folder:
    """Busca uma pasta garantindo que ela é do usuário. Se não, 404."""
    pasta = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.owner_id == user_id)
        .first()
    )
    if pasta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pasta não encontrada",
        )
    return pasta


@router.post("", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
def criar_pasta(
    dados: FolderCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Cria uma pasta. Se tiver pai, calcula a profundidade a partir dele e
    NÃO deixa passar do limite de níveis (config.MAX_FOLDER_DEPTH = 4).
    """
    if dados.parent_id is None:
        # Pasta raiz: nível 1.
        depth = 1
    else:
        # Pasta pai precisa existir E ser do usuário.
        pai = _buscar_pasta_do_usuario(dados.parent_id, user_id, db)

        # AQUI a trava dos 4 níveis: se o pai já está no nível máximo,
        # o filho seria o nível 5 — barra.
        if pai.depth >= settings.MAX_FOLDER_DEPTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Limite de {settings.MAX_FOLDER_DEPTH} níveis atingido",
            )
        depth = pai.depth + 1

    pasta = Folder(
        name=dados.name,
        owner_id=user_id,
        parent_id=dados.parent_id,
        depth=depth,
        color=dados.color,
    )
    db.add(pasta)
    db.commit()
    db.refresh(pasta)
    return pasta


@router.get("", response_model=list[FolderTree])
def listar_arvore(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Devolve a árvore inteira do usuário: só as pastas raiz, com os filhos
    aninhados dentro (o Pydantic monta a hierarquia sozinho).
    """
    raizes = (
        db.query(Folder)
        .filter(Folder.owner_id == user_id, Folder.parent_id.is_(None))
        .all()
    )
    return raizes


@router.get("/{folder_id}", response_model=FolderTree)
def ver_pasta(
    folder_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Devolve uma pasta específica com a sub-árvore dela."""
    return _buscar_pasta_do_usuario(folder_id, user_id, db)


@router.patch("/{folder_id}", response_model=FolderOut)
def renomear_pasta(
    folder_id: int,
    dados: FolderUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Renomeia e/ou troca a cor de uma pasta — só os campos enviados mudam.

    color usa model_fields_set (não `is not None`) porque null é um valor
    válido e intencional aqui: é como o frontend pede "volta pra cor
    padrão". Com `is not None`, dar PATCH com color=null nunca resetaria
    nada — ficaria indistinguível de "não mandei esse campo".
    """
    pasta = _buscar_pasta_do_usuario(folder_id, user_id, db)
    if dados.name is not None:
        pasta.name = dados.name
    if "color" in dados.model_fields_set:
        pasta.color = dados.color
    db.commit()
    db.refresh(pasta)
    return pasta


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_pasta(
    folder_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Exclui a pasta E tudo que está dentro dela (subpastas e decks),
    por causa do cascade configurado no model. Cuidado: é em cascata.
    """
    pasta = _buscar_pasta_do_usuario(folder_id, user_id, db)
    db.delete(pasta)
    db.commit()
