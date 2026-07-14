from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user_id
from app.models import Card, Deck, Review
from app.models.card import calcular_content_hash
from app.schemas.ai import GenerateRequest
from app.schemas.card import CardCreate, CardOut, CardTutorResponse, CardUpdate
from app.services.ai import IAError, QuotaExceededError, gerar_cards_completos
from app.services.tutor_service import explicar_conceito_breve

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
        gerados = gerar_cards_completos(dados.text, dados.quantity, user_id, db)
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


@router.post("/cards/{card_id}/tutor", response_model=CardTutorResponse)
def tutor_explicar_conceito(
    card_id: int,
    action: str = Query("explain"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Botão "Explicar" do Modo Revelar -- explicação curta (≤3 frases,
    ver explicar_conceito_breve em tutor_service.py) do conceito por trás
    do verso do card, pensada pra não quebrar o fluxo de quem está
    revelando cards em sequência.

    Endpoint simplificado, deliberadamente separado de
    POST /study/cards/{id}/tutor (Tutor Inteligente completo -- até 2
    parágrafos, markdown, cacheado em Card.tutor_explanation, usado pelo
    modal "Perguntar ao Tutor" do Modo Aprender): são dois contextos de
    UX diferentes (inline vs modal) com requisitos de tamanho/cache
    diferentes, por isso duas funções e dois endpoints em vez de um só
    parametrizado.

    `action` só aceita 'explain' hoje -- existe como parâmetro pra
    deixar espaço pra outras ações (ex: 'analyze', via
    tutor_service.analisar_feedback) sem quebrar compatibilidade depois.
    """
    if action != "explain":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"action '{action}' não suportada -- use 'explain'",
        )

    card = _card_do_usuario(card_id, user_id, db)

    try:
        explicacao = explicar_conceito_breve(card.front, card.back, user_id, db)
    except QuotaExceededError as e:
        # Precisa vir ANTES de "except IAError" -- QuotaExceededError é
        # subclasse dela (ver ai.py), e a mensagem certa aqui é "espere
        # até amanhã", não a genérica abaixo.
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    except IAError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    return CardTutorResponse(explanation=explicacao)


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
