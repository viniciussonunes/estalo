import random
from datetime import date, datetime, timezone
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Card, Deck, Review, User
from app.models.review_history import ReviewHistory
from app.schemas.study import (
    HistoryEntry, QuizOption, QuizQuestion, RevealCard,
    ReviewAnswer, ReviewResult, SessaoConcluida, StudyCard, StudyStats,
)
from app.services.ai import IAError, gerar_explicacoes, gerar_quiz
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


@router.get("/decks/{deck_id}/next", response_model=Union[StudyCard, SessaoConcluida])
def proximo_card(
    deck_id: int,
    incluir_dominados: bool = Query(False, description="Se true, dominados (reps≥2) entram na fila"),
    limite_diario: int = Query(50, ge=1, le=500, description="Máximo de cards revisados por dia"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _deck_do_usuario(deck_id, user, db)
    hoje = datetime.utcnow().date()
    inicio_do_dia = datetime(hoje.year, hoje.month, hoje.day, 0, 0, 0)

    # --- Tarefa 3: conta revisões feitas hoje neste deck ---
    revisoes_hoje = (
        db.query(func.count(ReviewHistory.id))
        .join(Card, ReviewHistory.card_id == Card.id)
        .filter(
            ReviewHistory.user_id == user.id,
            Card.deck_id == deck_id,
            ReviewHistory.avaliado_em >= inicio_do_dia,
        )
        .scalar()
    ) or 0

    if revisoes_hoje >= limite_diario:
        return SessaoConcluida(
            motivo="limite_diario",
            revisoes_hoje=revisoes_hoje,
            limite_diario=limite_diario,
        )

    # --- Prioridade via CASE WHEN ---
    # 0=Crítico, 1=Hoje, 2=Novo, 3=Validando
    prioridade_com_novo = case(
        (Review.id.is_(None),                2),  # Novo (sem review)
        (func.date(Review.due_date) < hoje,  0),  # Crítico
        (func.date(Review.due_date) == hoje, 1),  # Hoje
        else_=3,                                   # Validando
    )

    query = (
        db.query(Card, Review, prioridade_com_novo.label("prio"))
        .outerjoin(
            Review,
            (Review.card_id == Card.id) & (Review.user_id == user.id),
        )
        .filter(Card.deck_id == deck_id)
    )

    if not incluir_dominados:
        query = query.filter(
            (Review.id.is_(None))
            | (Review.repetitions < 2)
            | (func.date(Review.due_date) <= hoje)
        )

    # --- Tarefa 2: randomização dentro da mesma prioridade ---
    # Carrega todos os candidatos para descobrir a menor prioridade disponível,
    # depois sorteia aleatoriamente entre os que estão nessa prioridade.
    candidatos = query.all()

    if not candidatos:
        return SessaoConcluida(
            motivo="sem_cards",
            revisoes_hoje=revisoes_hoje,
            limite_diario=limite_diario,
        )

    # Menor valor de prioridade = mais urgente
    prio_min = min(row[2] for row in candidatos)
    top_tier = [row for row in candidatos if row[2] == prio_min]

    # Shuffle pseudo-aleatório dentro do tier para evitar previsibilidade
    card, review, _ = random.choice(top_tier)

    due = review.due_date if review else datetime.utcnow()
    reps = review.repetitions if review else 0

    return StudyCard(
        card_id=card.id,
        front=card.front,
        back=card.back,
        due_date=due,
        repetitions=reps,
        revisoes_hoje=revisoes_hoje,
        limite_diario=limite_diario,
    )


def _classificar_status(repetitions: int, due_date: datetime, hoje: "date") -> str:
    if repetitions == 0:
        return "novo"
    if repetitions == 1:
        return "validando"
    if due_date.date() < hoje:
        return "critico"
    return "dominado"


@router.post("/cards/{card_id}/answer", response_model=ReviewResult)
def responder_card(
    card_id: int,
    resposta: ReviewAnswer,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id == card_id, Deck.owner_id == user.id)
        .first()
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card não encontrado")

    try:
        quality = resposta.quality_efetivo()
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    # difficulty na escala 1-4 (para log e retorno)
    difficulty = resposta.difficulty or {1: 1, 3: 2, 4: 3, 5: 4}.get(quality, 2)

    review = _pegar_ou_criar_review(card, user, db)
    hoje = datetime.utcnow().date()

    estado_atual = SM2State(
        ease_factor=review.ease_factor,
        interval=review.interval,
        repetitions=review.repetitions,
        due_date=review.due_date,
    )

    # "Esqueci" (difficulty=1 / quality≤2) → due_date = agora para virar Crítico imediato
    novo = calcular_proxima_revisao(estado_atual, quality)
    if quality <= 2:
        novo = SM2State(
            ease_factor=novo.ease_factor,
            interval=1,
            repetitions=0,
            due_date=datetime.utcnow(),  # vence agora → Crítico na próxima query
        )

    # Grava log imutável antes de sobrescrever o estado
    db.add(ReviewHistory(
        user_id=user.id,
        card_id=card.id,
        difficulty=difficulty,
        quality=quality,
        reps_antes=review.repetitions,
        intervalo_antes=review.interval,
        reps_depois=novo.repetitions,
        intervalo_depois=novo.interval,
        ease_factor_depois=novo.ease_factor,
        nova_due_date=novo.due_date,
        status=_classificar_status(novo.repetitions, novo.due_date, hoje),
    ))

    # Atualiza estado SM-2
    review.ease_factor  = novo.ease_factor
    review.interval     = novo.interval
    review.repetitions  = novo.repetitions
    review.due_date     = novo.due_date
    review.last_reviewed = datetime.utcnow()
    db.commit()

    status_novo = _classificar_status(novo.repetitions, novo.due_date, hoje)
    return ReviewResult(
        card_id=card.id,
        interval=novo.interval,
        ease_factor=novo.ease_factor,
        repetitions=novo.repetitions,
        next_due=novo.due_date,
        status=status_novo,
        difficulty_usada=difficulty,
    )


@router.get("/decks/{deck_id}/stats", response_model=StudyStats)
def estatisticas(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _deck_do_usuario(deck_id, user, db)
    agora = datetime.utcnow()
    hoje_data = agora.date()

    cards = db.query(Card).filter(Card.deck_id == deck_id).all()

    # Carrega todas as reviews do usuário para este deck em uma única query
    card_ids = [c.id for c in cards]
    reviews = {
        r.card_id: r
        for r in db.query(Review)
        .filter(Review.user_id == user.id, Review.card_id.in_(card_ids))
        .all()
    } if card_ids else {}

    novos = validando = dominados = criticos = hoje = due_now = 0

    for card in cards:
        review = reviews.get(card.id)

        if review is None:
            # Nunca estudado → Novo
            novos += 1
            due_now += 1
            continue

        reps = review.repetitions
        due = review.due_date

        # Fase
        if reps == 0:
            novos += 1
        elif reps == 1:
            validando += 1
        else:
            dominados += 1

        # Status temporal (só para cards já estudados ao menos uma vez)
        if reps > 0:
            due_data = due.date()
            if due_data < hoje_data:
                # Venceu antes de hoje → Crítico (prioridade máxima)
                criticos += 1
                due_now += 1
            elif due_data == hoje_data:
                # Vence hoje → Revisão do Dia
                hoje += 1
                due_now += 1

    total = len(cards)
    return StudyStats(
        total_cards=total,
        novos=novos,
        validando=validando,
        dominados=dominados,
        criticos=criticos,
        hoje=hoje,
        # campos legados para compatibilidade com frontend atual
        due_now=due_now,
        new_cards=novos,
        validating=validando,
        dominated=dominados,
    )


@router.get("/cards/{card_id}/history", response_model=list[HistoryEntry])
def historico_card(
    card_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retorna o histórico de avaliações de um card, do mais recente ao mais antigo."""
    card = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id == card_id, Deck.owner_id == user.id)
        .first()
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card não encontrado")

    return (
        db.query(ReviewHistory)
        .filter(ReviewHistory.user_id == user.id, ReviewHistory.card_id == card_id)
        .order_by(ReviewHistory.avaliado_em.desc())
        .limit(limit)
        .all()
    )


@router.post("/decks/{deck_id}/quiz", response_model=list[QuizQuestion])
def gerar_quiz_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _deck_do_usuario(deck_id, user, db)
    cards = db.query(Card).filter(Card.deck_id == deck_id).all()
    if not cards:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "O deck não tem cards para gerar um quiz")

    random.shuffle(cards)
    cards_selecionados = cards[:20]
    cards_data = [
        {"card_id": c.id, "front": c.front, "back": c.back}
        for c in cards_selecionados
    ]

    try:
        resultado = gerar_quiz(cards_data)
    except IAError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    # Mapa card_id → repetitions para incluir a fase atual
    reps_map: dict[int, int] = {}
    for card in cards_selecionados:
        review = (
            db.query(Review)
            .filter(Review.user_id == user.id, Review.card_id == card.id)
            .first()
        )
        reps_map[card.id] = review.repetitions if review else 0

    card_ids_validos = {c.id for c in cards}
    questoes = []
    for item in resultado:
        if item["card_id"] not in card_ids_validos:
            continue
        opcoes = [item["correct"]] + item["distractors"]
        random.shuffle(opcoes)
        letras = ["A", "B", "C", "D"]
        opts = [QuizOption(letter=letras[i], text=opcoes[i]) for i in range(len(opcoes))]
        correct_letter = letras[opcoes.index(item["correct"])]
        questoes.append(QuizQuestion(
            card_id=item["card_id"],
            question=item["question"],
            options=opts,
            correct_letter=correct_letter,
            explanation=item["explanation"],
            repetitions=reps_map.get(item["card_id"], 0),
        ))

    return questoes


@router.post("/decks/{deck_id}/reveal", response_model=list[RevealCard])
def gerar_reveal_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _deck_do_usuario(deck_id, user, db)
    cards = db.query(Card).filter(Card.deck_id == deck_id).all()
    if not cards:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "O deck não tem cards para gerar explicações")

    cards_limitados = cards[:20]
    cards_data = [
        {"card_id": c.id, "front": c.front, "back": c.back}
        for c in cards_limitados
    ]

    try:
        resultado = gerar_explicacoes(cards_data)
    except IAError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    explicacao_map = {item["card_id"]: item["explanation"] for item in resultado}
    return [
        RevealCard(
            card_id=c.id,
            front=c.front,
            back=c.back,
            explanation=explicacao_map.get(c.id, ""),
        )
        for c in cards_limitados
    ]
