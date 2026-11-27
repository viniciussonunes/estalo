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
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.erros_ia import erro_http_de_ia
from app.dependencies import get_current_user_id
from app.models import Card, Deck, DeckAudio
from app.models.deck_audio import calcular_hash_do_deck
from app.services.ai import IAError
from app.services.roteiro_audio import VOZES, gerar_roteiro, tamanho_do_bloco
from app.services import audio_storage
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
        # Fase 3: quantos blocos o servidor tem guardados. Igual ao total =
        # o áudio inteiro está no servidor, e qualquer aparelho baixa sem
        # gastar cota (a tela faz isso sozinha, sem perguntar).
        "blocos_no_servidor": sum(1 for b in (audio.blocos_mp3 or []) if b),
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
    urls_velhas: list[str] = []
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
        # Os blocos do roteiro antigo não servem pro novo: saem do banco
        # agora e do Blob depois do commit. created_at é a VERSÃO do
        # roteiro (o app compara com o que guardou e o caminho no Blob
        # inclui) -- antes o refazer não a mudava, e um aparelho podia
        # reaproveitar blocos da conversa velha.
        urls_velhas = audio_storage.urls_de(audio.blocos_mp3)
        audio.roteiro = blocos
        audio.content_hash = hash_atual
        audio.blocos_mp3 = None
        audio.created_at = datetime.utcnow()
    db.commit()
    db.refresh(audio)
    audio_storage.apagar(urls_velhas)  # só depois do commit: se falhar, o banco não perdeu nada
    return _resumo(audio, hash_atual)


@router.post("/bloco/{indice}")
def gravar_bloco(
    deck_id: int,
    indice: int,
    formato: str = Query("pcm", pattern="^(pcm|mp3)$"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Entrega UM bloco do áudio -- do Blob, se já está lá; senão, grava.

    Com `formato=mp3` (o app a partir da fase 3), devolve MP3 e guarda o
    bloco no Blob. Se ele JÁ está guardado, devolve o guardado sem gravar
    nada: é assim que o segundo aparelho baixa o áudio sem gastar cota, e
    é o mesmo caminho da gravação -- o app não precisa saber a diferença.

    Sem `formato` (o app da fase 1, ainda em cache em algum aparelho),
    devolve PCM cru como sempre: esse app trata a resposta como PCM, e um
    MP3 tocaria como chiado. Ele não reaproveita o Blob (não teria como
    decodificar o MP3), mas o bloco gravado pra ele é guardado mesmo
    assim, pro próximo aparelho.

    Cabeçalhos: X-Taxa-Amostragem (taxa) e X-Amostras (duração em
    amostras, que o MP3 não diz sem decodificar).
    """
    _deck_do_usuario(deck_id, user_id, db)
    audio = db.query(DeckAudio).filter(DeckAudio.deck_id == deck_id).first()
    if audio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Este deck ainda não tem roteiro.")
    if not 0 <= indice < len(audio.roteiro):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bloco não existe neste roteiro.")

    blocos = list(audio.blocos_mp3 or [])
    blocos += [None] * (len(audio.roteiro) - len(blocos))
    guardado = blocos[indice]

    if formato == "mp3" and guardado:
        mp3 = audio_storage.ler(guardado["url"])
        if mp3 is not None:
            return _resposta_mp3(mp3, guardado["taxa"], guardado["amostras"], origem="servidor")
        # Não leu (Blob fora, arquivo sumido): grava de novo em vez de
        # deixar a pessoa sem áudio. Custa cota, mas é o caso raro.

    try:
        pcm, taxa = sintetizar_bloco(audio.roteiro[indice]["falas"], user_id=user_id, db=db, vozes=VOZES)
    except IAError as e:
        raise erro_http_de_ia(e, f"tts_bloco_{indice}")
    taxa = taxa or TAXA_PADRAO
    amostras = len(pcm) // 2
    mp3 = audio_storage.codificar_mp3(pcm, taxa)

    url = audio_storage.guardar(audio_storage.caminho_do_bloco(user_id, deck_id, audio, indice), mp3)
    if url:
        blocos[indice] = {"url": url, "amostras": amostras, "taxa": taxa, "bytes": len(mp3)}
        # Lista NOVA, não a mesma mutada: o SQLAlchemy só percebe que uma
        # coluna JSON mudou quando ela recebe outro objeto.
        audio.blocos_mp3 = blocos
        db.commit()

    if formato == "mp3":
        return _resposta_mp3(mp3, taxa, amostras, origem="gravado")
    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={"X-Taxa-Amostragem": str(taxa), "X-Amostras": str(amostras)},
    )


def _resposta_mp3(mp3: bytes, taxa: int, amostras: int, origem: str) -> Response:
    return Response(
        content=mp3,
        media_type="audio/mpeg",
        headers={
            "X-Taxa-Amostragem": str(taxa),
            "X-Amostras": str(amostras),
            # "servidor" = veio do Blob, não gastou cota; "gravado" = nasceu agora
            "X-Origem": origem,
        },
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def apagar_audio(deck_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Esquece o roteiro e o áudio guardado no servidor.

    Os arquivos do Blob saem depois do commit, pelo evento de sessão em
    audio_storage -- o mesmo que cobre a exclusão do deck e da pasta. O
    MP3 no aparelho é apagado pelo próprio app.
    """
    _deck_do_usuario(deck_id, user_id, db)
    audio = db.query(DeckAudio).filter(DeckAudio.deck_id == deck_id).first()
    if audio is not None:
        db.delete(audio)
        db.commit()
