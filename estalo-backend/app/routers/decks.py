"""
CRUD de decks.

Mesmo padrão das pastas: tudo protegido e isolado por usuário. Um deck pode
morar dentro de uma pasta (qualquer nível) ou ficar solto. Se for pra uma
pasta, a gente confere que a pasta é do próprio usuário.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Deck, Folder, User
from app.schemas.deck import DeckCreate, DeckOut, DeckUpdate

router = APIRouter(prefix="/decks", tags=["Decks"])


def _buscar_deck_do_usuario(deck_id: int, user: User, db: Session) -> Deck:
    deck = (
        db.query(Deck)
        .filter(Deck.id == deck_id, Deck.owner_id == user.id)
        .first()
    )
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck não encontrado")
    return deck


def _validar_pasta(folder_id: int | None, user: User, db: Session) -> None:
    """Se o deck vai pra uma pasta, ela precisa existir e ser do usuário."""
    if folder_id is None:
        return
    existe = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.owner_id == user.id)
        .first()
    )
    if existe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pasta não encontrada")


@router.post("", response_model=DeckOut, status_code=status.HTTP_201_CREATED)
def criar_deck(
    dados: DeckCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validar_pasta(dados.folder_id, user, db)
    deck = Deck(
        title=dados.title,
        description=dados.description,
        folder_id=dados.folder_id,
        owner_id=user.id,
    )
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return deck


@router.get("", response_model=list[DeckOut])
def listar_decks(
    folder_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Lista os decks do usuário. Se passar ?folder_id=X, filtra só os daquela
    pasta. Sem o filtro, traz todos.
    """
    q = db.query(Deck).filter(Deck.owner_id == user.id)
    if folder_id is not None:
        q = q.filter(Deck.folder_id == folder_id)
    return q.all()


@router.get("/{deck_id}", response_model=DeckOut)
def ver_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _buscar_deck_do_usuario(deck_id, user, db)


@router.patch("/{deck_id}", response_model=DeckOut)
def atualizar_deck(
    deck_id: int,
    dados: DeckUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _buscar_deck_do_usuario(deck_id, user, db)
    if dados.folder_id is not None:
        _validar_pasta(dados.folder_id, user, db)

    # Atualiza só os campos que vieram preenchidos.
    if dados.title is not None:
        deck.title = dados.title
    if dados.description is not None:
        deck.description = dados.description
    if dados.folder_id is not None:
        deck.folder_id = dados.folder_id

    db.commit()
    db.refresh(deck)
    return deck


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Exclui o deck e todos os cards dentro dele (cascade)."""
    deck = _buscar_deck_do_usuario(deck_id, user, db)
    db.delete(deck)
    db.commit()
