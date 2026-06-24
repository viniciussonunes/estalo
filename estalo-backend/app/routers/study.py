"""
Rota de estudo — aqui o motor SM-2 finalmente liga.

O ciclo de estudo:
1. GET  /study/decks/{deck_id}/next  → a API te entrega o próximo card vencido
2. você vê a frente, pensa, vê o verso
3. POST /study/cards/{card_id}/answer → você manda a nota (0 a 5)
4. o SM-2 recalcula quando esse card volta a aparecer

"Card vencido" = a data de revisão (due_date) já chegou. Card que você acertou
fácil vai ter due_date lá na frente, some da fila. Card que errou volta amanhã.

Detalhe importante (criar sob demanda): a ficha de revisão (Review) de um card
só nasce na primeira vez que você estuda ele. Card nunca aberto = card "novo".
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Card, Deck, Review, User
from app.schemas.study import ReviewAnswer, ReviewResult, StudyCard, StudyStats
from app.services.sm2 import SM2State, calcular_proxima_revisao

router = APIRouter(prefix="/study", tags=["Estudo"])


def _deck_do_usuario(deck_id: int, user: User, db: Session) -> Deck:
    deck = (
        db.query(Deck)
        .filter(Deck.id == deck_id, Deck.owner_id == user.id)
        .first()
    )
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck não encontrado")
    return deck


def _pegar_ou_criar_review(card: Card, user: User, db: Session) -> Review:
    """
    Busca a ficha de revisão do par (usuário, card). Se não existe ainda
    (card novo), cria com os valores iniciais do SM-2 e due_date = agora,
    pra ele já entrar na fila de hoje.
    """
    review = (
        db.query(Review)
        .filter(Review.user_id == user.id, Review.card_id == card.id)
        .first()
    )
    if review is None:
        review = Review(user_id=user.id, card_id=card.id, due_date=datetime.utcnow())
        db.add(review)
        db.commit()
        db.refresh(review)
    return review


@router.get("/decks/{deck_id}/next", response_model=StudyCard | None)
def proximo_card(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Entrega o próximo card pra revisar neste deck. Prioridade:
    1. Cards já vencidos (due_date <= agora)
    2. Cards novos (sem ficha de revisão ainda)
    Se não houver nada pra estudar agora, devolve null.
    """
    _deck_do_usuario(deck_id, user, db)
    agora = datetime.utcnow()

    cards = db.query(Card).filter(Card.deck_id == deck_id).all()

    melhor_card = None
    melhor_due = None
    for card in cards:
        review = (
            db.query(Review)
            .filter(Review.user_id == user.id, Review.card_id == card.id)
            .first()
        )
        # Card novo (sem review) entra como vencido agora.
        due = review.due_date if review else agora
        reps = review.repetitions if review else 0

        if due <= agora:
            # Pega o que venceu há mais tempo primeiro.
            if melhor_due is None or due < melhor_due:
                melhor_due = due
                melhor_card = StudyCard(
                    card_id=card.id,
                    front=card.front,
                    back=card.back,
                    due_date=due,
                    repetitions=reps,
                )

    return melhor_card


@router.post("/cards/{card_id}/answer", response_model=ReviewResult)
def responder_card(
    card_id: int,
    resposta: ReviewAnswer,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Recebe a nota (0 a 5), roda o SM-2 e salva o novo estado.
    Devolve quando o card vai voltar a aparecer.
    """
    # Confere que o card existe e é do usuário (via deck).
    card = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id == card_id, Deck.owner_id == user.id)
        .first()
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card não encontrado")

    review = _pegar_ou_criar_review(card, user, db)

    # Roda o motor com o estado atual + a nota.
    estado_atual = SM2State(
        ease_factor=review.ease_factor,
        interval=review.interval,
        repetitions=review.repetitions,
        due_date=review.due_date,
    )
    novo = calcular_proxima_revisao(estado_atual, resposta.quality)

    # Salva o novo estado.
    review.ease_factor = novo.ease_factor
    review.interval = novo.interval
    review.repetitions = novo.repetitions
    review.due_date = novo.due_date
    review.last_reviewed = datetime.utcnow()
    db.commit()

    return ReviewResult(
        card_id=card.id,
        interval=novo.interval,
        ease_factor=novo.ease_factor,
        repetitions=novo.repetitions,
        next_due=novo.due_date,
    )


@router.get("/decks/{deck_id}/stats", response_model=StudyStats)
def estatisticas(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resumo do deck: total de cards, quantos estão vencidos e quantos são novos."""
    _deck_do_usuario(deck_id, user, db)
    agora = datetime.utcnow()

    cards = db.query(Card).filter(Card.deck_id == deck_id).all()
    total = len(cards)
    novos = 0
    vencidos = 0
    for card in cards:
        review = (
            db.query(Review)
            .filter(Review.user_id == user.id, Review.card_id == card.id)
            .first()
        )
        if review is None:
            novos += 1
            vencidos += 1  # card novo conta como pronto pra estudar
        elif review.due_date <= agora:
            vencidos += 1

    return StudyStats(total_cards=total, due_now=vencidos, new_cards=novos)
