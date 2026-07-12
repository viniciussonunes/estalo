"""
Router do módulo Challenge (tabela paralela a cards) -- endpoints básicos
pra validar a estrutura ponta a ponta (model -> schema -> banco -> HTTP),
mais a geração automática via IA (POST /challenges/generate), hoje usada
principalmente pelo Mentor de Inglês Ativo (type="ENGLISH_TUTOR", default).

Sem nenhum import de/para app/routers/cards.py, app/services/tutor_service.py
ou app/routers/study.py: este router não sabe que o fluxo de estudo de TI
existe, e nada ali sabe que Challenge existe. A geração por IA passa por
challenge_service.py, que por sua vez usa o Adaptador de provedor
(app/services/ai.py::_chamar_ia) -- o MESMO ponto de entrada de IA usado
por todo o resto da plataforma (cota diária, troca Gemini/OpenAI via
IA_PROVIDER), não uma chamada de IA paralela e desalinhada.

Mesmo padrão de ownership dos outros routers (_deck_do_usuario local,
não compartilhado) -- ver cards.py/study.py pra por que cada router
mantém sua própria cópia em vez de importar de um lugar só.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user_id
from app.models import Challenge, Deck
from app.schemas.challenge import ChallengeCreate, ChallengeGenerateRequest, ChallengeResponse
from app.services.ai import IAError, QuotaExceededError
from app.services.challenge_service import gerar_challenge

router = APIRouter(prefix="/challenges", tags=["Challenges"])


def _deck_do_usuario(deck_id: int, user_id: int, db: Session) -> Deck:
    deck = (
        db.query(Deck)
        .filter(Deck.id == deck_id, Deck.owner_id == user_id)
        .first()
    )
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck não encontrado")
    return deck


@router.post("", response_model=ChallengeResponse, status_code=status.HTTP_201_CREATED)
def criar_challenge(
    dados: ChallengeCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _deck_do_usuario(dados.deck_id, user_id, db)

    challenge = Challenge(
        deck_id=dados.deck_id,
        type=dados.type,
        content=dados.content,
        explanation=dados.explanation,
        tutor_explanation=dados.tutor_explanation,
        language_level=dados.language_level,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


@router.post("/generate", response_model=ChallengeResponse, status_code=status.HTTP_201_CREATED)
def gerar_challenge_endpoint(
    dados: ChallengeGenerateRequest,
    response: Response,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Gera um Challenge por IA a partir de raw_content + type + depth +
    language_level (ver challenge_service.gerar_challenge pro prompt e a
    validação/correção do JSON devolvido). Mesmos códigos de erro que o
    resto da API usa pra IA (ver tutor_card/explicar_erro_card em
    study.py): 429 se a cota diária estourou, 503 pra qualquer outra
    falha de IA (chave ausente, rede fora, ou JSON que nem a tentativa de
    correção conseguiu salvar).

    preview_only=True: nada é persistido (ver o service) -- devolve
    200 (não 201, já que nenhum recurso foi de fato criado) com
    id/created_at nulos no corpo. preview_only=False (padrão): 201,
    igual a antes."""
    _deck_do_usuario(dados.deck_id, user_id, db)

    try:
        challenge = gerar_challenge(
            dados.deck_id, dados.raw_content, dados.type, user_id, db,
            depth=dados.depth, language_level=dados.language_level,
            preview_only=dados.preview_only,
        )
    except QuotaExceededError as e:
        # Precisa vir ANTES de "except IAError" -- QuotaExceededError é
        # subclasse dela (ver ai.py), e a mensagem certa aqui é "espere
        # até amanhã", não a genérica abaixo.
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    except IAError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    if dados.preview_only:
        response.status_code = status.HTTP_200_OK

    return challenge


@router.get("", response_model=list[ChallengeResponse])
def listar_challenges(
    deck_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Sem deck_id, lista os challenges de TODOS os decks do usuário
    (join em Deck pra nunca vazar challenge de outro usuário); com
    deck_id, escopa num deck só (e 404 se ele não existir ou não for
    do usuário logado)."""
    query = db.query(Challenge).join(Deck, Challenge.deck_id == Deck.id).filter(Deck.owner_id == user_id)

    if deck_id is not None:
        _deck_do_usuario(deck_id, user_id, db)
        query = query.filter(Challenge.deck_id == deck_id)

    return query.order_by(Challenge.id).all()
