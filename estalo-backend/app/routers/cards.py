"""
CRUD de cards.

Cards moram dentro de decks. Por isso criar e listar usam a URL aninhada
/decks/{deck_id}/cards — fica explícito de qual deck é o card. Mexer num
card específico usa /cards/{card_id}.

Em toda operação a gente confere que o deck (e portanto o card) é do usuário.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Card, Deck, User
from app.schemas.ai import GenerateRequest
from app.schemas.card import CardCreate, CardOut, CardUpdate
from app.services.ai import IAError, gerar_cards

router = APIRouter(tags=["Cards"])


def _deck_do_usuario(deck_id: int, user: User, db: Session) -> Deck:
    deck = (
        db.query(Deck)
        .filter(Deck.id == deck_id, Deck.owner_id == user.id)
        .first()
    )
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck não encontrado")
    return deck


def _card_do_usuario(card_id: int, user: User, db: Session) -> Card:
    # Junta card com deck e confere o dono pelo deck.
    card = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id == card_id, Deck.owner_id == user.id)
        .first()
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card não encontrado")
    return card


@router.post(
    "/decks/{deck_id}/cards",
    response_model=CardOut,
    status_code=status.HTTP_201_CREATED,
)
def criar_card(
    deck_id: int,
    dados: CardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _deck_do_usuario(deck_id, user, db)  # confere o dono
    card = Card(
        front=dados.front,
        back=dados.back,
        source=dados.source,
        deck_id=deck_id,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


@router.post(
    "/decks/{deck_id}/cards/generate",
    response_model=list[CardOut],
    status_code=status.HTTP_201_CREATED,
)
def gerar_cards_ia(
    deck_id: int,
    dados: GenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Gera cards a partir de um texto usando IA (Gemini) e salva no deck,
    já marcados com source='ai'. Sua dor #1 resolvida.
    """
    _deck_do_usuario(deck_id, user, db)  # confere o dono

    try:
        gerados = gerar_cards(dados.text, dados.quantity)
    except IAError as e:
        # 502 = "eu (a API) tentei falar com outro serviço e deu ruim".
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    novos = [
        Card(front=g["front"], back=g["back"], source="ai", deck_id=deck_id)
        for g in gerados
    ]
    db.add_all(novos)
    db.commit()
    for c in novos:
        db.refresh(c)
    return novos


@router.get("/decks/{deck_id}/cards", response_model=list[CardOut])
def listar_cards(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _deck_do_usuario(deck_id, user, db)
    return db.query(Card).filter(Card.deck_id == deck_id).all()


@router.get("/cards/{card_id}", response_model=CardOut)
def ver_card(
    card_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _card_do_usuario(card_id, user, db)


@router.patch("/cards/{card_id}", response_model=CardOut)
def atualizar_card(
    card_id: int,
    dados: CardUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = _card_do_usuario(card_id, user, db)
    if dados.front is not None:
        card.front = dados.front
    if dados.back is not None:
        card.back = dados.back
    db.commit()
    db.refresh(card)
    return card


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_card(
    card_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = _card_do_usuario(card_id, user, db)
    db.delete(card)
    db.commit()
