"""
Áudio do Ouvir guardado no servidor (fase 3): MP3 no Vercel Blob privado.

--- O que mudou em relação à fase 1 ---
Na fase 1 o servidor devolvia PCM cru e o NAVEGADOR comprimia pra MP3
(lamejs). O áudio só existia no aparelho de quem gravou: no segundo
aparelho, era gravar de novo e pagar a cota de novo. Agora o servidor
comprime (lameenc, wheel pronto pro Linux da Vercel, sem compilar) e
guarda cada bloco. Medido num preview em 27/11/2026: 75s de áudio viram
0,6 MB em 0,26s; gravar no Blob 0,19s; ler 0,06s.

Efeito colateral bom: cada bloco que desce pro celular caiu de ~3,6 MB
(PCM) pra ~0,6 MB. O limite de ~4,5 MB de resposta da função deixou de
ser o teto apertado do tamanho do bloco.

--- Por que privado, e por que o download passa pelo backend ---
O áudio é o conteúdo dos cards de alguém. No Blob privado não existe URL
pública: sem o token, 403 (verificado). O SDK de Python não gera links
assinados (só o de JavaScript), então quem serve o bloco a outro
aparelho é o backend, lendo do Blob -- 0,6 MB cabe com folga.

--- Por que nada aqui pode derrubar a gravação ---
O plano é Hobby: 1 GB, 10 GB de download e 2.000 operações "avançadas"
(cada gravação é uma) por mês, SEM cobrança extra -- estourou, o Blob
recusa até o mês virar. Se o Blob recusar, o áudio continua funcionando
como na fase 1: chega ao aparelho e fica lá. Guardar no servidor é um
bônus, nunca um requisito; por isso toda função aqui engole o erro e
avisa o Sentry em vez de propagar.
"""
import os

import lameenc
import sentry_sdk
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.deck_audio import DeckAudio

# 64 kbps mono: o mesmo da fase 1 (medido lá: abaixo disso a voz começa a
# chiar nos sibilantes). Mantido pra quem já ouvia não notar diferença.
KBPS = 64


def codificar_mp3(pcm: bytes, taxa: int) -> bytes:
    """PCM 16-bit mono -> MP3. Determinístico, sem rede."""
    enc = lameenc.Encoder()
    enc.set_bit_rate(KBPS)
    enc.set_in_sample_rate(taxa)
    enc.set_channels(1)
    enc.set_quality(2)  # 2 = alta qualidade; o custo de CPU medido é irrisório
    enc.silence()       # sem isto o LAME escreve no stdout da função
    return bytes(enc.encode(pcm) + enc.flush())


def blob_disponivel() -> bool:
    """Há credencial do Blob neste ambiente?

    Na Vercel a variável vem do armazenamento ligado ao projeto; em dev e
    nos testes, normalmente não existe -- e aí nem tentamos falar com a
    rede: o áudio segue o caminho da fase 1.
    """
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN"))


def caminho_do_bloco(user_id: int, deck_id: int, audio: DeckAudio, indice: int) -> str:
    """Onde o bloco mora no Blob.

    A versão do roteiro (created_at) entra no caminho: um roteiro reescrito
    nunca aponta pra um arquivo do anterior, nem por engano.
    """
    versao = int(audio.created_at.timestamp()) if audio.created_at else 0
    return f"ouvir/u{user_id}/d{deck_id}/a{audio.id}-{versao}/b{indice}.mp3"


def guardar(caminho: str, mp3: bytes) -> str | None:
    """Grava no Blob privado. Devolve a URL, ou None se não deu."""
    if not blob_disponivel():
        return None
    try:
        from vercel.blob.sync import put_blob
        r = put_blob(caminho, mp3, access="private", content_type="audio/mpeg", allow_overwrite=True)
        return r.url
    except Exception as e:  # cota, rede, armazenamento suspenso: tudo vira "não guardou"
        sentry_sdk.capture_exception(e)
        print(f"[audio_storage] não guardou {caminho}: {e!r}")
        return None


def ler(url: str) -> bytes | None:
    """Lê um bloco do Blob, ou None se não deu (aí o bloco é regravado)."""
    if not blob_disponivel():
        return None
    try:
        from vercel.blob.sync import get_blob
        g = get_blob(url, access="private")
        corpo = g.body if isinstance(g.body, (bytes, bytearray)) else g.body.read()
        return bytes(corpo)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        print(f"[audio_storage] não leu {url}: {e!r}")
        return None


def apagar(urls: list[str]) -> None:
    """Apaga arquivos do Blob. Melhor esforço: falhar só deixa um órfão."""
    urls = [u for u in urls if u]
    if not urls or not blob_disponivel():
        return
    try:
        from vercel.blob.sync import delete_blob
        delete_blob(urls)  # uma chamada pra todos: cada chamada é uma operação do plano
    except Exception as e:
        sentry_sdk.capture_exception(e)
        print(f"[audio_storage] não apagou {len(urls)} arquivo(s): {e!r}")


def urls_de(blocos: list | None) -> list[str]:
    return [b["url"] for b in (blocos or []) if isinstance(b, dict) and b.get("url")]


# --- Apagar do Blob quando o roteiro some do banco ---------------------
#
# Um DeckAudio sai do banco por três caminhos: o botão de remover, a
# exclusão do deck e a exclusão da pasta (que apaga os decks em cascata).
# Em vez de lembrar de apagar os arquivos em cada um -- e esquecer o
# próximo que aparecer --, a sessão anota as URLs de todo DeckAudio
# apagado e só apaga do Blob DEPOIS do commit: se o banco desfizer a
# exclusão, os arquivos continuam lá.

@event.listens_for(Session, "after_flush")
def _anotar_apagados(sessao, _contexto):
    for obj in sessao.deleted:
        if isinstance(obj, DeckAudio):
            sessao.info.setdefault("blobs_a_apagar", []).extend(urls_de(obj.blocos_mp3))


@event.listens_for(Session, "after_commit")
def _apagar_depois_do_commit(sessao):
    urls = sessao.info.pop("blobs_a_apagar", None)
    if urls:
        apagar(urls)


@event.listens_for(Session, "after_rollback")
def _esquecer_no_rollback(sessao):
    sessao.info.pop("blobs_a_apagar", None)
