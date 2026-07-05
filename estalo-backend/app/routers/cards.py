from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user_id
from app.models import Card, Deck, Review
from app.models.card import calcular_content_hash
from app.schemas.ai import GenerateRequest
from app.schemas.card import CardCreate, CardOut, CardUpdate
from app.services.ai import IAError, gerar_cards_completos

router = APIRouter(tags=["Cards"])


def _deck_do_usuario(deck_id: int, user_id: int, db: Session) -> Deck:
    deck = (
        db.query(Deck)
        .filter(Deck.id == deck_id, Deck.owner_id == user_id)
        .first()
    )
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck não encontrado")
    return deck


def _card_do_usuario(card_id: int, user_id: int, db: Session) -> Card:
    card = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id == card_id, Deck.owner_id == user_id)
        .first()
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card não encontrado")
    return card


def _card_out(card: Card, user_id: int, db: Session) -> CardOut:
    """Constrói CardOut incluindo o estado SM-2 do usuário."""
    review = (
        db.query(Review)
        .filter(Review.user_id == user_id, Review.card_id == card.id)
        .first()
    )
    return CardOut(
        id=card.id,
        front=card.front,
        back=card.back,
        deck_id=card.deck_id,
        source=card.source,
        created_at=card.created_at,
        options=card.options,
        explanation=card.explanation,
        repetitions=review.repetitions if review else 0,
    )


@router.post(
    "/decks/{deck_id}/cards",
    response_model=CardOut,
    status_code=status.HTTP_201_CREATED,
)
def criar_card(
    deck_id: int,
    dados: CardCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _deck_do_usuario(deck_id, user_id, db)
    card = Card(
        front=dados.front,
        back=dados.back,
        source=dados.source,
        deck_id=deck_id,
        content_hash=calcular_content_hash(dados.front, dados.back),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return _card_out(card, user_id, db)


@router.post(
    "/decks/{deck_id}/cards/generate",
    response_model=list[CardOut],
    status_code=status.HTTP_201_CREATED,
)
def gerar_cards_ia(
    deck_id: int,
    dados: GenerateRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Gera cards completos com IA: front, back, 3 distratores e explicação.
    Tudo salvo no banco — o Modo Aprender carrega instantaneamente depois.
    """
    _deck_do_usuario(deck_id, user_id, db)

    try:
        gerados = gerar_cards_completos(dados.text, dados.quantity)
    except IAError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    novos = [
        Card(
            front=g["front"],
            back=g["back"],
            options=g["distractors"],
            explanation=g["explanation"],
            source="ai",
            deck_id=deck_id,
            content_hash=calcular_content_hash(g["front"], g["back"]),
        )
        for g in gerados
    ]
    db.add_all(novos)
    db.commit()
    for c in novos:
        db.refresh(c)
    return [_card_out(c, user_id, db) for c in novos]


@router.get("/decks/{deck_id}/cards", response_model=list[CardOut])
def listar_cards(
    deck_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _deck_do_usuario(deck_id, user_id, db)
    cards = db.query(Card).filter(Card.deck_id == deck_id).all()
    return [_card_out(c, user_id, db) for c in cards]


@router.get("/cards/{card_id}", response_model=CardOut)
def ver_card(
    card_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    card = _card_do_usuario(card_id, user_id, db)
    return _card_out(card, user_id, db)


@router.patch("/cards/{card_id}", response_model=CardOut)
def atualizar_card(
    card_id: int,
    dados: CardUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    card = _card_do_usuario(card_id, user_id, db)
    if dados.front is not None:
        card.front = dados.front
    if dados.back is not None:
        card.back = dados.back
    if dados.front is not None or dados.back is not None:
        # Recalcula com os valores JÁ atualizados de card.front/card.back
        # acima — cobre tanto editar só um dos dois campos quanto os dois.
        card.content_hash = calcular_content_hash(card.front, card.back)
    db.commit()
    db.refresh(card)
    return _card_out(card, user_id, db)


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_card(
    card_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    card = _card_do_usuario(card_id, user_id, db)
    db.delete(card)
    db.commit()
