from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Card, Deck, Folder, Review, User
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
    if folder_id is None:
        return
    existe = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.owner_id == user.id)
        .first()
    )
    if existe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pasta não encontrada")


def _memorization_pct(deck_id: int, user_id: int, db: Session) -> tuple[int, float]:
    """Retorna (total_cards, memorization_pct 0-100).

    Fases por card:
      - sem Review ou repetitions == 0  → Fase 1 / Novo      (0 %)
      - repetitions == 1                → Fase 2 / Validando  (50 %)
      - repetitions >= 2               → Fase 3 / Dominado   (100 %)
    """
    cards = db.query(Card).filter(Card.deck_id == deck_id).all()
    total = len(cards)
    if total == 0:
        return 0, 0.0

    soma = 0.0
    for card in cards:
        review = (
            db.query(Review)
            .filter(Review.user_id == user_id, Review.card_id == card.id)
            .first()
        )
        reps = review.repetitions if review else 0
        if reps == 1:
            soma += 50.0
        elif reps >= 2:
            soma += 100.0

    return total, round(soma / total, 1)


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
    return DeckOut(
        id=deck.id,
        title=deck.title,
        description=deck.description,
        folder_id=deck.folder_id,
        created_at=deck.created_at,
    )


@router.get("", response_model=list[DeckOut])
def listar_decks(
    folder_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Deck).filter(Deck.owner_id == user.id)
    if folder_id is not None:
        q = q.filter(Deck.folder_id == folder_id)
    decks = q.all()

    resultado = []
    for deck in decks:
        total, pct = _memorization_pct(deck.id, user.id, db)
        resultado.append(DeckOut(
            id=deck.id,
            title=deck.title,
            description=deck.description,
            folder_id=deck.folder_id,
            created_at=deck.created_at,
            total_cards=total,
            memorization_pct=pct,
        ))
    return resultado


@router.get("/{deck_id}", response_model=DeckOut)
def ver_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _buscar_deck_do_usuario(deck_id, user, db)
    total, pct = _memorization_pct(deck.id, user.id, db)
    return DeckOut(
        id=deck.id,
        title=deck.title,
        description=deck.description,
        folder_id=deck.folder_id,
        created_at=deck.created_at,
        total_cards=total,
        memorization_pct=pct,
    )


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
    if dados.title is not None:
        deck.title = dados.title
    if dados.description is not None:
        deck.description = dados.description
    if dados.folder_id is not None:
        deck.folder_id = dados.folder_id
    db.commit()
    db.refresh(deck)
    total, pct = _memorization_pct(deck.id, user.id, db)
    return DeckOut(
        id=deck.id,
        title=deck.title,
        description=deck.description,
        folder_id=deck.folder_id,
        created_at=deck.created_at,
        total_cards=total,
        memorization_pct=pct,
    )


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _buscar_deck_do_usuario(deck_id, user, db)
    db.delete(deck)
    db.commit()
