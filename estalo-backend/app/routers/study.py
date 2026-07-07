import random
from datetime import date, datetime, timedelta, timezone
from typing import Union
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user_id, get_user_timezone
from app.models import Card, Deck, Folder, Review
from app.models.explanation_cache import ExplanationCache
from app.models.review_history import ReviewHistory
from app.models.study_session import StudySession
from app.routers.folders import _buscar_pasta_do_usuario
from app.schemas.error_explanation import (
    ExplanationFeedbackRequest, ExplanationOut, ExplanationRequest,
)
from app.schemas.study import (
    EnrichCardsRequest, EnrichCardsResponse, EnrichedCard,
    GlobalReviewCard, HistoryEntry, QuizOption, QuizQuestion, RevealCard,
    ReviewAnswer, ReviewResult, SessaoConcluida, StreakOut, StudyCard,
    StudySessionLog, StudySessionOut, StudyStats, TutorResponse,
)
from app.services.ai import IAError, QuotaExceededError, gerar_explicacoes, gerar_quiz
from app.services.error_explanation_service import explicar_erro, refinar_explicacao
from app.services.sm2 import SM2State, calcular_proxima_revisao
from app.services.study_service import get_all_deck_ids_in_folder
from app.services.tutor_service import explicar_card

router = APIRouter(prefix="/study", tags=["Estudo"])


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


def _agora_utc() -> datetime:
    """Equivalente não-deprecated de datetime.utcnow() que preserva
    naive-UTC: datetime.now(timezone.utc) devolve um datetime AWARE, mas
    toda coluna DateTime deste projeto é naive — .replace(tzinfo=None)
    descarta a tzinfo, devolvendo o MESMO valor que utcnow() já devolvia,
    sem risco de TypeError comparando com o que vem do banco."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hoje_no_fuso(tz: ZoneInfo) -> date:
    """'Hoje' no fuso do usuário — a virada acontece à meia-noite local
    dele, não à meia-noite UTC."""
    return datetime.now(tz).date()


def _data_no_fuso(dt: datetime, tz: ZoneInfo) -> date:
    """Converte um datetime armazenado (naive, convenção UTC em todo o
    projeto) pra data de calendário no fuso do usuário."""
    return dt.replace(tzinfo=timezone.utc).astimezone(tz).date()



@router.get("/decks/{deck_id}/next", response_model=Union[StudyCard, SessaoConcluida])
def proximo_card(
    deck_id: int,
    incluir_dominados: bool = Query(False, description="Se true, dominados (reps≥2) entram na fila"),
    limite_diario: int = Query(50, ge=1, le=500, description="Máximo de cards revisados por dia"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    tz: ZoneInfo = Depends(get_user_timezone),
):
    _deck_do_usuario(deck_id, user_id, db)
    hoje = _hoje_no_fuso(tz)
    # Meia-noite LOCAL do usuário, convertida pra UTC naive — é isso que
    # compara contra avaliado_em (sempre armazenado em UTC).
    inicio_do_dia_local = datetime(hoje.year, hoje.month, hoje.day, tzinfo=tz)
    inicio_do_dia = inicio_do_dia_local.astimezone(timezone.utc).replace(tzinfo=None)

    # --- Tarefa 3: conta revisões feitas hoje neste deck ---
    revisoes_hoje = (
        db.query(func.count(ReviewHistory.id))
        .join(Card, ReviewHistory.card_id == Card.id)
        .filter(
            ReviewHistory.user_id == user_id,
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

    # --- Prioridade e elegibilidade calculadas em Python, não em SQL ---
    # func.date(Review.due_date) truncaria a data DENTRO do banco, no fuso
    # de armazenamento (UTC) — não dá pra deslocar isso por usuário de forma
    # portável entre SQLite e Postgres. Carrega os candidatos do deck
    # (escopo pequeno, um deck por vez) e decide tudo aqui.
    linhas = (
        db.query(Card, Review)
        .outerjoin(Review, (Review.card_id == Card.id) & (Review.user_id == user_id))
        .filter(Card.deck_id == deck_id)
        .all()
    )

    # 0=Crítico, 1=Hoje, 2=Novo, 3=Validando
    candidatos = []
    for card, review in linhas:
        if review is None:
            prio = 2
            elegivel = True
        else:
            due_local = _data_no_fuso(review.due_date, tz)
            prio = 0 if due_local < hoje else 1 if due_local == hoje else 3
            elegivel = incluir_dominados or review.repetitions < 2 or due_local <= hoje
        if elegivel:
            candidatos.append((card, review, prio))

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

    due = review.due_date if review else _agora_utc()
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


@router.get("/global-reviews", response_model=list[GlobalReviewCard])
def revisao_global(
    folder_id: int | None = Query(
        None, description="Se informado, restringe a fila a essa pasta e suas subpastas (Estudo por Pasta). Sem isso, todos os decks do usuário (Modo Global)."
    ),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Fila Única de Revisão ("Estudar Tudo"), pra alimentar o Modo Aprender.

    Só cards que JÁ têm progresso e estão vencidos (Review.due_date <=
    agora) — cards nunca estudados ficam de fora de propósito. Eles moram
    só dentro de cada pasta; misturá-los aqui é o que causava a ansiedade
    do "número gigante" que motivou esse ajuste. Como o card precisa ter
    Review pra entrar, o JOIN é interno (não outer) — sem prioridade SM-2
    pra calcular, o due_date sozinho já ordena "mais vencido primeiro"
    dentro do mesmo deck.

    Devolve até 15 de uma vez (não é mais 1-por-chamada como o /next): o
    Modo Aprender consome lote, não fila stateless. Cada item já inclui
    options/explanation crus do Card — o mesmo contrato de CardOut que
    montarFila() no frontend já sabe montar em pergunta de múltipla
    escolha; cards sem esses dois campos pré-gerados são descartados lá,
    igual já acontece hoje pro Modo Aprender por-deck.

    folder_id (opcional) liga o "Estudo por Pasta": restringe a fila aos
    decks daquela pasta e de todas as suas subpastas (recursivo — ver
    get_all_deck_ids_in_folder em services/study_service.py). 404 se a
    pasta não existir ou não for do usuário; lista vazia (sem erro) se a
    pasta existir mas não tiver nenhum deck com cards vencidos.
    """
    agora = _agora_utc()

    deck_ids_da_pasta = None
    if folder_id is not None:
        _buscar_pasta_do_usuario(folder_id, user_id, db)  # 404 se não existir/não for do usuário
        deck_ids_da_pasta = get_all_deck_ids_in_folder(folder_id, user_id, db)
        if not deck_ids_da_pasta:
            return []  # pasta (e subpastas) sem nenhum deck — nada pra buscar

    query = (
        db.query(Card, Review, Deck, Folder)
        .join(Deck, Card.deck_id == Deck.id)
        .join(Review, (Review.card_id == Card.id) & (Review.user_id == user_id))
        .outerjoin(Folder, Deck.folder_id == Folder.id)
        .filter(Deck.owner_id == user_id, Review.due_date <= agora)
    )
    if deck_ids_da_pasta is not None:
        query = query.filter(Deck.id.in_(deck_ids_da_pasta))

    linhas = (
        query
        .order_by(
            # Folder.name.is_(None) evita depender da ordenação de NULL
            # default do banco (SQLite e Postgres discordam nisso) — decks
            # dentro de pasta (A-Z) vêm antes dos soltos na raiz.
            Folder.name.is_(None),
            Folder.name.asc(),
            Deck.title.asc(),
            Review.due_date.asc(),
        )
        .limit(15)
        .all()
    )

    return [
        GlobalReviewCard(
            card_id=card.id,
            front=card.front,
            back=card.back,
            due_date=review.due_date,
            repetitions=review.repetitions,
            options=card.options,
            explanation=card.explanation,
            deck_name=deck.title,
            deck_color=folder.color if folder else None,
        )
        for card, review, deck, folder in linhas
    ]


def _classificar_status(repetitions: int, due_date: datetime, hoje: date, tz: ZoneInfo) -> str:
    if repetitions == 0:
        return "novo"
    if repetitions == 1:
        return "validando"
    if _data_no_fuso(due_date, tz) < hoje:
        return "critico"
    return "dominado"


def _history_para_result(h: ReviewHistory, tz: ZoneInfo) -> ReviewResult:
    """Reconstrói um ReviewResult a partir de uma entrada de histórico (resposta idempotente)."""
    hoje = _hoje_no_fuso(tz)
    return ReviewResult(
        card_id=h.card_id,
        interval=h.intervalo_depois,
        ease_factor=h.ease_factor_depois,
        repetitions=h.reps_depois,
        next_due=h.nova_due_date,
        status=_classificar_status(h.reps_depois, h.nova_due_date, hoje, tz),
        difficulty_usada=h.difficulty,
        idempotente=True,
    )


@router.post("/cards/{card_id}/answer", response_model=ReviewResult)
def responder_card(
    card_id: int,
    resposta: ReviewAnswer,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    tz: ZoneInfo = Depends(get_user_timezone),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
):
    # --- Tarefa 1: Idempotência via X-Request-ID ---
    # Se o cliente enviar um ID único por requisição, uma segunda chamada com o
    # mesmo ID retorna o resultado original sem reprocessar o card.
    if x_request_id:
        entrada_existente = (
            db.query(ReviewHistory)
            .filter(
                ReviewHistory.user_id == user_id,
                ReviewHistory.request_id == x_request_id,
            )
            .first()
        )
        if entrada_existente:
            return _history_para_result(entrada_existente, tz)

    # --- Verifica existência e posse do card ---
    card = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id == card_id, Deck.owner_id == user_id)
        .first()
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card não encontrado")

    try:
        quality = resposta.quality_efetivo()
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    difficulty = resposta.difficulty or {1: 1, 3: 2, 4: 3, 5: 4}.get(quality, 2)

    # --- Tarefa 2: Lock de linha para evitar race condition ---
    # with_for_update() emite SELECT ... FOR UPDATE — garante que apenas uma
    # transação por vez leia e modifique este Review. Outras requisições
    # concorrentes aguardam o commit antes de prosseguir.
    review = (
        db.query(Review)
        .filter(Review.user_id == user_id, Review.card_id == card_id)
        .with_for_update()
        .first()
    )

    agora = _agora_utc()
    hoje = _hoje_no_fuso(tz)

    if review is None:
        # Card nunca estudado — cria o estado inicial dentro da transação atual
        review = Review(user_id=user_id, card_id=card_id, due_date=agora)
        db.add(review)
        db.flush()  # persiste no banco sem commit para que o lock cubra o INSERT

    # --- Tarefa 3: Validação de estado ---
    # Compara só a DATA (não o datetime) para não bloquear sessões feitas em
    # horários diferentes do mesmo dia ou antes da hora exata do due_date.
    # Só vale pro Modo Estudo (SM-2 clássico) — ele seleciona cards por due_date
    # via /next, então essa trava protege a cadência da repetição espaçada.
    # O Modo Aprender quiza TODOS os cards do deck de uma vez, sem filtrar por
    # due_date (ver montarFila() no frontend) — pra ele, essa trava não faz
    # sentido e só bloqueava silenciosamente o avanço de fase numa segunda
    # sessão no mesmo dia. Por isso ignorar_elegibilidade existe.
    card_elegivel = (
        resposta.ignorar_elegibilidade
        or review.repetitions == 0                          # Novo — sempre pode
        or _data_no_fuso(review.due_date, tz) <= hoje        # due venceu hoje (local) ou antes
    )
    if not card_elegivel:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Card não está na fila de estudo. Próxima revisão: {_data_no_fuso(review.due_date, tz).isoformat()}",
        )

    # --- Cálculo SM-2 ---
    estado_atual = SM2State(
        ease_factor=review.ease_factor,
        interval=review.interval,
        repetitions=review.repetitions,
        due_date=review.due_date,
    )

    novo = calcular_proxima_revisao(estado_atual, quality)
    if quality <= 2:
        # "Esqueci" → Crítico imediato
        novo = SM2State(
            ease_factor=novo.ease_factor,
            interval=1,
            repetitions=0,
            due_date=agora,
        )

    status_novo = _classificar_status(novo.repetitions, novo.due_date, hoje, tz)

    # --- Bloco atômico: histórico + atualização do estado ---
    # Tudo no mesmo commit; se qualquer parte falhar, o banco reverte.
    db.add(ReviewHistory(
        user_id=user_id,
        card_id=card.id,
        difficulty=difficulty,
        quality=quality,
        reps_antes=estado_atual.repetitions,
        intervalo_antes=estado_atual.interval,
        reps_depois=novo.repetitions,
        intervalo_depois=novo.interval,
        ease_factor_depois=novo.ease_factor,
        nova_due_date=novo.due_date,
        status=status_novo,
        request_id=x_request_id,   # None se header ausente (sem unicidade imposta)
    ))

    review.ease_factor   = novo.ease_factor
    review.interval      = novo.interval
    review.repetitions   = novo.repetitions
    review.due_date      = novo.due_date
    review.last_reviewed = agora
    db.commit()

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
    user_id: int = Depends(get_current_user_id),
    tz: ZoneInfo = Depends(get_user_timezone),
):
    _deck_do_usuario(deck_id, user_id, db)
    hoje_data = _hoje_no_fuso(tz)

    cards = db.query(Card).filter(Card.deck_id == deck_id).all()

    # Carrega todas as reviews do usuário para este deck em uma única query
    card_ids = [c.id for c in cards]
    reviews = {
        r.card_id: r
        for r in db.query(Review)
        .filter(Review.user_id == user_id, Review.card_id.in_(card_ids))
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

        # Status temporal — dimensão independente da fase, não "só pra
        # reps>0": o Crítico Imediato (study.py, responder_card) reseta
        # repetitions pra 0 quando o usuário erra, com due_date=agora. Sem
        # essa checagem valer pra reps==0, um card que acabou de falhar e
        # está genuinamente vencido ficava invisível pra criticos/hoje —
        # contava só como "novo", igual um card nunca estudado, embora os
        # dois sejam bem diferentes (um tem histórico e prioridade real).
        due_data = _data_no_fuso(due, tz)
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


@router.get("/decks/stats", response_model=dict[int, StudyStats])
def estatisticas_varios_decks(
    ids: str = Query(..., description="IDs de deck separados por vírgula, ex: 1,2,3"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    tz: ZoneInfo = Depends(get_user_timezone),
):
    """Versão em lote de GET /decks/{id}/stats — calcula pra vários decks
    de uma vez com quantidade FIXA de queries (independente de quantos
    decks ou cards existam). Substitui o padrão antigo do frontend de
    disparar 1 request HTTP por deck (statsMultiplos)."""
    try:
        deck_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ids inválido")

    deck_ids_do_usuario = {
        d.id for d in db.query(Deck.id)
        .filter(Deck.owner_id == user_id, Deck.id.in_(deck_ids))
        .all()
    }
    deck_ids = [i for i in deck_ids if i in deck_ids_do_usuario]
    if not deck_ids:
        return {}

    hoje_data = _hoje_no_fuso(tz)

    cards = db.query(Card).filter(Card.deck_id.in_(deck_ids)).all()
    card_ids = [c.id for c in cards]
    reviews = {
        r.card_id: r
        for r in db.query(Review)
        .filter(Review.user_id == user_id, Review.card_id.in_(card_ids))
        .all()
    } if card_ids else {}

    por_deck = {
        deck_id: {"total": 0, "novos": 0, "validando": 0, "dominados": 0, "criticos": 0, "hoje": 0, "due_now": 0}
        for deck_id in deck_ids
    }

    for card in cards:
        acc = por_deck[card.deck_id]
        acc["total"] += 1
        review = reviews.get(card.id)

        if review is None:
            acc["novos"] += 1
            acc["due_now"] += 1
            continue

        reps = review.repetitions
        due = review.due_date

        if reps == 0:
            acc["novos"] += 1
        elif reps == 1:
            acc["validando"] += 1
        else:
            acc["dominados"] += 1

        # Ver comentário equivalente em estatisticas(): status temporal
        # independe da fase, senão um card resetado pelo Crítico Imediato
        # (reps=0, due_date=agora) fica invisível pra criticos/hoje.
        due_data = _data_no_fuso(due, tz)
        if due_data < hoje_data:
            acc["criticos"] += 1
            acc["due_now"] += 1
        elif due_data == hoje_data:
            acc["hoje"] += 1
            acc["due_now"] += 1

    return {
        deck_id: StudyStats(
            total_cards=acc["total"],
            novos=acc["novos"],
            validando=acc["validando"],
            dominados=acc["dominados"],
            criticos=acc["criticos"],
            hoje=acc["hoje"],
            due_now=acc["due_now"],
            new_cards=acc["novos"],
            validating=acc["validando"],
            dominated=acc["dominados"],
        )
        for deck_id, acc in por_deck.items()
    }


@router.get("/heatmap-stats", response_model=dict[str, int])
def heatmap_stats(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    tz: ZoneInfo = Depends(get_user_timezone),
):
    """Quantidade de avaliações do usuário por dia (YYYY-MM-DD, no fuso do
    usuário), últimos 30 dias.

    func.date() truncaria a data DENTRO do banco, no fuso de armazenamento
    (UTC) — não dá pra deslocar isso por usuário de forma portável entre
    SQLite e Postgres. Por isso busca uma janela um pouco mais larga em UTC
    (32 dias, pra cobrir a borda que o fuso do usuário desloca) e agrupa em
    Python, já convertido pro fuso certo.
    """
    desde = _agora_utc() - timedelta(days=32)
    linhas = (
        db.query(ReviewHistory.avaliado_em)
        .filter(ReviewHistory.user_id == user_id, ReviewHistory.avaliado_em >= desde)
        .all()
    )
    limite = _hoje_no_fuso(tz) - timedelta(days=30)
    contagem: dict[str, int] = {}
    for (avaliado_em,) in linhas:
        dia_local = _data_no_fuso(avaliado_em, tz)
        if dia_local < limite:
            continue
        chave = dia_local.isoformat()
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


@router.get("/streak", response_model=StreakOut)
def streak(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    tz: ZoneInfo = Depends(get_user_timezone),
):
    """Sequência de dias seguidos com pelo menos uma avaliação (ReviewHistory),
    no fuso do usuário. Ver heatmap_stats() acima sobre por que a truncagem
    por dia acontece em Python, não em func.date()."""
    linhas = (
        db.query(ReviewHistory.avaliado_em)
        .filter(ReviewHistory.user_id == user_id)
        .all()
    )
    dias = sorted({_data_no_fuso(avaliado_em, tz) for (avaliado_em,) in linhas})
    if not dias:
        return StreakOut(current_streak=0, longest_streak=0)

    # Maior sequência já registrada, olhando o histórico inteiro
    maior = sequencia = 1
    for anterior, atual in zip(dias, dias[1:]):
        sequencia = sequencia + 1 if (atual - anterior).days == 1 else 1
        maior = max(maior, sequencia)

    # Sequência atual: só conta se o último dia estudado foi hoje ou ontem;
    # senão a sequência "quebrou" e current_streak é 0.
    hoje = _hoje_no_fuso(tz)
    if dias[-1] < hoje - timedelta(days=1):
        atual_streak = 0
    else:
        atual_streak = 1
        for i in range(len(dias) - 1, 0, -1):
            if (dias[i] - dias[i - 1]).days == 1:
                atual_streak += 1
            else:
                break

    return StreakOut(current_streak=atual_streak, longest_streak=maior)


@router.get("/cards/{card_id}/history", response_model=list[HistoryEntry])
def historico_card(
    card_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Retorna o histórico de avaliações de um card, do mais recente ao mais antigo."""
    card = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id == card_id, Deck.owner_id == user_id)
        .first()
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card não encontrado")

    return (
        db.query(ReviewHistory)
        .filter(ReviewHistory.user_id == user_id, ReviewHistory.card_id == card_id)
        .order_by(ReviewHistory.avaliado_em.desc())
        .limit(limit)
        .all()
    )


@router.post("/cards/{card_id}/tutor", response_model=TutorResponse)
def tutor_card(
    card_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Explicação didática sob demanda (Tutor Inteligente — ver
    app/services/tutor_service.py). Cacheada em Card.tutor_explanation: da
    segunda vez em diante que o usuário pedir ajuda neste card, a resposta
    já salva volta na hora, sem chamar o Gemini de novo."""
    card = _card_do_usuario(card_id, user_id, db)

    if card.tutor_explanation:
        return TutorResponse(explanation=card.tutor_explanation)

    front, back = card.front, card.back
    # Encerra a transação de leitura ANTES da chamada à IA (até ~52s no pior
    # caso: 2 tentativas de 25s). Achado testando de verdade: o listener de
    # "begin" do SQLite (database.py) emite BEGIN IMMEDIATE em QUALQUER
    # transação, leitura incluída — segurar a sessão aberta até aqui trava
    # (por até busy_timeout=5s, depois falha) qualquer outra request que
    # toque o banco enquanto o Gemini responde. Sem efeito em produção
    # (Postgres não serializa leituras assim), mas evitava até testar local.
    db.commit()

    try:
        explicacao = explicar_card(front, back, user_id, db)
    except QuotaExceededError as e:
        # Precisa vir ANTES de "except IAError" -- QuotaExceededError é
        # subclasse dela (ver ai.py), e a mensagem certa aqui é "espere até
        # amanhã", não "tente de novo já", que o except genérico abaixo diz.
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    except IAError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Tutor indisponível no momento. Tente novamente em instantes.",
        )

    card.tutor_explanation = explicacao
    db.commit()

    return TutorResponse(explanation=explicacao)


def _explanation_cache_do_usuario(
    card_id: int, alternativa_escolhida: str, user_id: int, db: Session,
) -> ExplanationCache:
    cache = (
        db.query(ExplanationCache)
        .join(Card, ExplanationCache.card_id == Card.id)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(
            ExplanationCache.card_id == card_id,
            ExplanationCache.alternativa_escolhida == alternativa_escolhida,
            Deck.owner_id == user_id,
        )
        .first()
    )
    if cache is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhuma explicação encontrada pra dar feedback")
    return cache


@router.post("/cards/{card_id}/error-explanation", response_model=ExplanationOut)
def explicar_erro_card(
    card_id: int,
    dados: ExplanationRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Tutor Inteligente Evolutivo (ver app/services/error_explanation_service.py):
    explica por que UMA alternativa específica está errada, com cache
    versionado por (card, alternativa) que evolui via feedback (ver
    /error-explanation/feedback abaixo)."""
    card = _card_do_usuario(card_id, user_id, db)
    front, back = card.front, card.back
    # Mesmo motivo do tutor_card acima: não segura a transação aberta
    # durante a chamada lenta à IA. Sem efeito aqui na prática, já que um
    # Hit de cache nem chega a chamar o Gemini -- mas mantém o mesmo hábito
    # defensivo em todo endpoint que pode acabar chamando _chamar_gemini.
    db.commit()

    try:
        return explicar_erro(card_id, front, back, dados.alternativa_escolhida, user_id, db)
    except QuotaExceededError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    except IAError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Explicação indisponível no momento. Tente novamente em instantes.",
        )


@router.post("/cards/{card_id}/error-explanation/feedback", response_model=ExplanationOut)
def feedback_explicacao_erro(
    card_id: int,
    dados: ExplanationFeedbackRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """👍: não muda nada, a explicação em cache já está boa como está.
    👎 (com motivo): pede uma versão refinada ao Gemini (ver
    error_explanation_service.refinar_explicacao — idempotente por
    conteúdo e limitado a MAX_VERSAO tentativas por alternativa)."""
    cache = _explanation_cache_do_usuario(card_id, dados.alternativa_escolhida, user_id, db)

    if dados.positivo:
        return ExplanationOut(explanation=cache.texto_explicacao_atual, versao=cache.versao)

    if not dados.motivo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Feedback negativo precisa de um motivo")

    card = db.get(Card, card_id)
    front, back = card.front, card.back
    db.commit()

    try:
        return refinar_explicacao(cache, front, back, dados.motivo, user_id, db)
    except QuotaExceededError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    except IAError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Não foi possível refinar a explicação agora. Tente novamente em instantes.",
        )


@router.post("/session/log", response_model=StudySessionOut, status_code=status.HTTP_201_CREATED)
def logar_sessao(
    dados: StudySessionLog,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Registra o resumo de uma rodada do Modo Aprender já encerrada.

    Insert puro, sem leitura prévia — ao contrário de responder_card() (que
    faz read-modify-write num Review existente e por isso precisa de lock de
    linha), aqui não há estado anterior pra disputar: cada chamada só
    adiciona uma linha nova, então não existe corrida possível.
    """
    sessao = StudySession(
        user_id=user_id,
        total_cards=dados.total_cards,
        acertos_primeira=dados.acertos_primeira,
        duracao_seg=dados.duracao_seg,
        modo=dados.modo,
    )
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


@router.post("/cards/enrich", response_model=EnrichCardsResponse)
def enriquecer_cards(
    dados: EnrichCardsRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Auto-cura: gera quiz (options/explanation) pra cards que já existem
    mas nasceram sem alternativas (criados manualmente, nunca passaram por
    "Gerar com IA"). Chamado pelo Aprender.jsx quando encontra, na fila que
    acabou de carregar, cards sem quiz pronto — em vez de simplesmente
    descartá-los, tenta reparar na hora.

    Reaproveita gerar_quiz() (services/ai.py), a mesma função já usada por
    POST /decks/{id}/quiz — a diferença é que aqui o resultado é persistido
    de volta no Card, não descartado ao fim da resposta.
    """
    cards = (
        db.query(Card)
        .join(Deck, Card.deck_id == Deck.id)
        .filter(Card.id.in_(dados.card_ids), Deck.owner_id == user_id)
        .all()
    )
    if not cards:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhum card encontrado")

    cards_data = [{"card_id": c.id, "front": c.front, "back": c.back} for c in cards]

    try:
        resultado = gerar_quiz(cards_data, user_id, db)
    except IAError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    cards_por_id = {c.id: c for c in cards}
    enriquecidos = []
    for item in resultado:
        card = cards_por_id.get(item["card_id"])
        if card is None:
            continue
        card.options = item["distractors"]
        card.explanation = item["explanation"]
        enriquecidos.append(EnrichedCard(
            card_id=item["card_id"],
            options=item["distractors"],
            explanation=item["explanation"],
        ))
    db.commit()

    ids_pedidos = {c.id for c in cards}
    ids_resolvidos = {e.card_id for e in enriquecidos}
    falhas = sorted(ids_pedidos - ids_resolvidos)

    return EnrichCardsResponse(enriched=enriquecidos, falhas=falhas)


@router.post("/decks/{deck_id}/quiz", response_model=list[QuizQuestion])
def gerar_quiz_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _deck_do_usuario(deck_id, user_id, db)
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
        resultado = gerar_quiz(cards_data, user_id, db)
    except IAError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    # Mapa card_id → repetitions para incluir a fase atual
    reps_map: dict[int, int] = {}
    for card in cards_selecionados:
        review = (
            db.query(Review)
            .filter(Review.user_id == user_id, Review.card_id == card.id)
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
    user_id: int = Depends(get_current_user_id),
):
    _deck_do_usuario(deck_id, user_id, db)
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
        resultado = gerar_explicacoes(cards_data, user_id, db)
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
