"""
Tela "Ouvir" — gera e serve o áudio de um deck (dois locutores).

--- Por que o cliente conduz o loop ---
Um episódio de 5 minutos não cabe numa função serverless: o maxDuration
é 60s e a locução roda a ~3,3x o tempo real. Então o trabalho sai
picado, e quem conduz a fila é o NAVEGADOR -- um POST por bloco. Mesma
escolha do importador de Anki (process-batch), pelo mesmo motivo: nada
roda em segundo plano num ambiente onde a função morre junto com a
resposta. Se a pessoa fechar a aba, para; ao voltar, o roteiro ainda
está aqui e ela continua do bloco que faltava.

--- Por que o áudio volta como bytes crus, não JSON ---
PCM custa 48 KB por segundo. Um bloco de 50s são 2,4 MB; em base64
dentro de um JSON viraria 3,2 MB, e o limite de corpo de resposta de uma
função serverless na Vercel é ~4,5 MB. Mandar binário puro economiza o
terço que o base64 desperdiça -- e é o terço que decide se cabe.

Comprimir pra MP3 fica a cargo do navegador: não existe ffmpeg no
runtime Python da Vercel, e empacotar um binário de dezenas de MB na
função pra economizar banda que o cliente já tem seria caro do lado
errado.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.erros_ia import erro_http_de_ia
from app.dependencies import get_current_user_id
from app.models import Card, Deck, DeckAudio
from app.models.deck_audio import calcular_hash_do_deck
from app.services.ai import IAError
from app.services.roteiro_audio import VOZES, gerar_roteiro, tamanho_do_bloco
from app.services.tts import TAXA_PADRAO, sintetizar_bloco

router = APIRouter(prefix="/decks/{deck_id}/audio", tags=["Áudio"])


def _deck_do_usuario(deck_id: int, user_id: int, db: Session) -> Deck:
    deck = db.query(Deck).filter(Deck.id == deck_id, Deck.owner_id == user_id).first()
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck não encontrado")
    return deck


def _cards_do_deck(deck_id: int, db: Session) -> list[Card]:
    return db.query(Card).filter(Card.deck_id == deck_id).order_by(Card.id).all()


def _pares_do_deck(deck_id: int, db: Session) -> list[tuple[str, str]]:
    """Frente e verso -- o que entra no retrato do deck (content_hash).

    As alternativas e a explicação ficam de fora do retrato de propósito:
    elas são regeradas pela auto-cura do quiz sem ninguém editar nada, e
    isso não pode acender "este áudio está atrasado" num deck que, pra
    quem estuda, não mudou.
    """
    return [(c.front, c.back) for c in _cards_do_deck(deck_id, db)]


def _resumo(audio: DeckAudio, hash_atual: str) -> dict:
    """O que a tela precisa saber sem baixar áudio nenhum."""
    blocos = audio.roteiro
    return {
        "existe": True,
        "criado_em": audio.created_at.isoformat() if audio.created_at else None,
        "desatualizado": audio.content_hash != hash_atual,
        "total_blocos": len(blocos),
        "capitulos": _capitulos(blocos),
    }


_SUFIXO_FASE_1 = " (continuação)"


def _capitulos(blocos: list[dict]) -> list[dict]:
    """Blocos de gravação agrupados em capítulos pra quem ouve.

    Um bloco longo é cortado em pedaços pra caber numa gravação, mas o
    pedaço não é assunto novo: vira parte do capítulo anterior, não uma
    linha "(continuação)" na lista. A tela busca áudio por `total_blocos`
    e usa esta lista só pra mostrar e posicionar, então agrupar aqui não
    muda nada na gravação.

    `indice` é o primeiro bloco do capítulo. Roteiros da fase 1 marcavam
    o pedaço no título ("X (continuação)") em vez de `continua`; os dois
    jeitos são entendidos.
    """
    capitulos: list[dict] = []
    for i, b in enumerate(blocos):
        # Com a pausa contada: a tela posiciona os capítulos na barra
        # pela proporção de caracteres, e 3s de silêncio são tempo.
        tamanho = tamanho_do_bloco(b["falas"])
        continua = b.get("continua") or b["titulo"].endswith(_SUFIXO_FASE_1)
        if continua and capitulos:
            capitulos[-1]["caracteres"] += tamanho
        else:
            capitulos.append({"indice": i, "titulo": b["titulo"].removesuffix(_SUFIXO_FASE_1),
                              "caracteres": tamanho})
    return capitulos


@router.get("")
def ver_audio(deck_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Estado do áudio deste deck. Nunca 404 — "não existe" é resposta."""
    _deck_do_usuario(deck_id, user_id, db)
    audio = db.query(DeckAudio).filter(DeckAudio.deck_id == deck_id).first()
    if audio is None:
        return {"existe": False}
    return _resumo(audio, calcular_hash_do_deck(_pares_do_deck(deck_id, db)))


@router.post("/roteiro", status_code=status.HTTP_201_CREATED)
def criar_roteiro(
    deck_id: int,
    refazer: bool = False,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Escreve (ou reescreve) o diálogo. Só texto — o áudio vem depois.

    Sem `refazer`, um roteiro que já existe é devolvido como está, mesmo
    desatualizado: regerar sozinho gastaria a cota de IA da pessoa sem
    ela pedir. Quem decide é a tela, que mostra o aviso de atrasado e
    oferece o botão.
    """
    deck = _deck_do_usuario(deck_id, user_id, db)
    cards_do_deck = _cards_do_deck(deck_id, db)
    pares = [(c.front, c.back) for c in cards_do_deck]
    if not pares:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este deck ainda não tem cards.")

    hash_atual = calcular_hash_do_deck(pares)
    audio = db.query(DeckAudio).filter(DeckAudio.deck_id == deck_id).first()
    if audio is not None and not refazer:
        return _resumo(audio, hash_atual)

    cards = [
        {"front": c.front, "back": c.back,
         "distractors": c.options or [], "explanation": c.explanation or ""}
        for c in cards_do_deck
    ]
    try:
        blocos = gerar_roteiro(deck.title, cards, user_id, db)
    except IAError as e:
        raise erro_http_de_ia(e, "roteiro_audio")

    if audio is None:
        audio = DeckAudio(deck_id=deck_id, roteiro=blocos, content_hash=hash_atual)
        db.add(audio)
    else:
        audio.roteiro = blocos
        audio.content_hash = hash_atual
    db.commit()
    db.refresh(audio)
    return _resumo(audio, hash_atual)


@router.post("/bloco/{indice}")
def gravar_bloco(
    deck_id: int,
    indice: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Grava UM bloco e devolve o PCM cru (16-bit mono).

    A taxa de amostragem vai no cabeçalho em vez de embutida num WAV: o
    cliente concatena vários blocos antes de codificar, e cabeçalho de
    WAV no meio de uma concatenação vira chiado audível.
    """
    _deck_do_usuario(deck_id, user_id, db)
    audio = db.query(DeckAudio).filter(DeckAudio.deck_id == deck_id).first()
    if audio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Este deck ainda não tem roteiro.")
    if not 0 <= indice < len(audio.roteiro):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bloco não existe neste roteiro.")

    bloco = audio.roteiro[indice]
    try:
        pcm, taxa = sintetizar_bloco(bloco["falas"], user_id=user_id, db=db, vozes=VOZES)
    except IAError as e:
        raise erro_http_de_ia(e, f"tts_bloco_{indice}")

    return Response(
        content=pcm,
        media_type="application/octet-stream",
        # Só a taxa. O título do bloco também viajava aqui, mutilado por um
        # encode("ascii") que comia os acentos ("segurança" -> "seguranca"),
        # e ninguém lia: os títulos dos capítulos vêm do JSON de _resumo().
        # Cabeçalho que nenhum cliente lê é código morto que parece
        # funcionalidade.
        headers={"X-Taxa-Amostragem": str(taxa or TAXA_PADRAO)},
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def apagar_audio(deck_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Esquece o roteiro. O MP3 no aparelho é apagado pelo próprio cliente."""
    _deck_do_usuario(deck_id, user_id, db)
    audio = db.query(DeckAudio).filter(DeckAudio.deck_id == deck_id).first()
    if audio is not None:
        db.delete(audio)
        db.commit()
