"""
Serviço de TTS — transforma um roteiro de diálogo em áudio PCM.

--- Por que um adaptador próprio, e não dentro de ai.py ---
ai.py é o adaptador de TEXTO: entra prompt, sai string. Aqui entra uma
lista de falas e sai áudio binário, com um eixo de comutação diferente --
não é "Gemini ou OpenAI", é "qual MODELO de TTS está de pé agora". Mesma
ideia, contrato incompatível; forçar os dois no mesmo adaptador deixaria
as duas coisas piores.

--- A bagunça que esta camada esconde ---
A mesma funcionalidade (dois locutores) tem DUAS APIs diferentes no
Gemini, e qual delas vale depende do modelo:

  FORMATO_FALAS  (3.8+)  cada fala é uma part com speechMetadata.speaker.
                         Modelos antigos respondem 400 "Speech metadata is
                         not supported for this model".
  FORMATO_BLOCO  (2.5)   o roteiro inteiro vai num texto só, prefixado por
                         "TTS the following conversation between A and B:".
                         O 3.8 responde 400 exigindo o speechMetadata.

Medido em 2026-11-05: o gemini-3.8-flash-tts estava devolvendo 503
("experiencing high demand") enquanto o 2.5 respondia normalmente. Ou
seja, isto não é teoria -- a lista TTS_MODELOS existe porque o modelo
mais novo cai, e cair sem reserva significa a tela de Ouvir quebrar.

--- Cota ---
Quem chama é que debita, via sintetizar(..., user_id=, db=). O custo real
do TTS é em tokens de ÁUDIO (~25 por segundo narrado, medido), não nos
tokens de texto que o quota_service conta hoje. Nesta fase debitamos a
estimativa de áudio no MESMO balde de texto: superestima, nunca
subestima, e garante que nenhum caminho gaste dinheiro sem medidor. O
medidor separado é fase 4 (ver docs do projeto).
"""
import base64
import math
import time

import httpx
import sentry_sdk

from app.core.config import settings
from app.services.ai import IAError, QuotaExceededError
from app.services.quota_service import check_and_consume_tokens

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

FORMATO_FALAS = "falas"   # 3.8+: uma part por fala, com speechMetadata.speaker
FORMATO_BLOCO = "bloco"   # 2.5:  roteiro inteiro num texto só

# Ordem = preferência. O primeiro que responder ganha. Testados um a um
# contra a API real; os que não aceitam dois locutores ficaram de fora.
TTS_MODELOS: tuple[tuple[str, str], ...] = (
    ("gemini-3.8-flash-tts", FORMATO_FALAS),
    ("gemini-2.5-flash-preview-tts", FORMATO_BLOCO),
    ("gemini-2.5-pro-preview-tts", FORMATO_BLOCO),
)

# Vozes pré-prontas do Gemini. Puck lê mais solto, Kore mais firme -- o
# contraste é o que faz o ouvinte distinguir quem fala sem precisar de
# nome na frente da fala.
VOZ_HOMEM = "Puck"
VOZ_MULHER = "Kore"

TAXA_PADRAO = 24000          # Hz, 16-bit mono -- o que a API devolve
BYTES_POR_SEGUNDO = TAXA_PADRAO * 2   # 48 KB por segundo de áudio

# Medido com diálogo real em pt-BR: 1138 caracteres de fala viraram 79,2s.
# A primeira medição dizia 18,0 e estava errada -- ela contava o cabeçalho
# "TTS the following conversation..." e os prefixos "Rafael: " junto com a
# fala. Aqui só entra texto que é de fato pronunciado.
CHARS_POR_SEGUNDO = 14.4
TOKENS_AUDIO_POR_SEGUNDO = 25  # medido (1148 tokens / 45.9s)

# O teto de um pedaço NÃO é o tempo de geração -- é o tamanho da resposta.
# A geração roda a ~3,3x o tempo real (79,2s de áudio em 23,7s), então o
# maxDuration de 60s da Vercel aguentaria bem mais. Quem aperta é o limite
# de ~4,5 MB no corpo de resposta de uma função serverless: PCM cru custa
# 48 KB/s, então 60s já são 2,9 MB e 90s estourariam. 50s deixa margem
# confortável, e é por isso que o roteiro é picado nesse tamanho.
MAX_SEGUNDOS_POR_PEDACO = 60
BYTES_MAX_RESPOSTA = 4_000_000

_RETRY_STATUS = {429, 500, 502, 503, 504}


class TTSError(IAError):
    """Falha ao gerar áudio.

    Subclassa IAError de propósito: os routers e o erro_http_de_ia já
    tratam IAError, então isto vira 503 com mensagem humana de graça.
    """


def estimar_segundos(falas: list[tuple[str, str]]) -> float:
    """Quantos segundos de áudio este roteiro deve virar."""
    return sum(len(texto) for _, texto in falas) / CHARS_POR_SEGUNDO


def estimar_tokens_audio(falas: list[tuple[str, str]]) -> int:
    return math.ceil(estimar_segundos(falas) * TOKENS_AUDIO_POR_SEGUNDO)


def _payload(falas: list[tuple[str, str]], vozes: dict[str, str], formato: str) -> dict:
    locutores = list(dict.fromkeys(q for q, _ in falas))  # ordem preservada, sem repetir
    config_vozes = [
        {"speaker": q, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": vozes[q]}}}
        for q in locutores
    ]
    generation = {
        "responseModalities": ["AUDIO"],
        "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": config_vozes}},
    }

    if formato == FORMATO_FALAS:
        parts = [{"text": t, "speechMetadata": {"speaker": q}} for q, t in falas]
    else:
        cabecalho = f"TTS the following conversation between {' and '.join(locutores)}:"
        corpo = "\n".join(f"{q}: {t}" for q, t in falas)
        parts = [{"text": f"{cabecalho}\n{corpo}"}]

    return {"contents": [{"parts": parts}], "generationConfig": generation}


def _extrair_pcm(dados: dict) -> tuple[bytes, int]:
    """Tira o áudio da resposta e devolve (pcm_cru, taxa).

    A API às vezes rotula o mimeType como audio/wav mesmo mandando PCM
    cru, e às vezes manda audio/L16;rate=24000. Em vez de confiar no
    rótulo, olhamos os bytes: se vier com cabeçalho RIFF de verdade, ele
    é removido -- quem consome aqui espera PCM puro, e um cabeçalho
    sobrando no meio de uma concatenação vira chiado audível.
    """
    try:
        parte = dados["candidates"][0]["content"]["parts"][0]["inlineData"]
        bruto = base64.b64decode(parte["data"])
    except (KeyError, IndexError, ValueError) as e:
        raise TTSError("Resposta de áudio veio em formato inesperado") from e

    mime = parte.get("mimeType", "")
    taxa = TAXA_PADRAO
    if "rate=" in mime:
        try:
            taxa = int(mime.split("rate=")[1].split(";")[0])
        except ValueError:
            pass

    if bruto[:4] == b"RIFF" and bruto[8:12] == b"WAVE":
        pos = 12
        while pos + 8 <= len(bruto):
            nome = bruto[pos:pos + 4]
            tamanho = int.from_bytes(bruto[pos + 4:pos + 8], "little")
            if nome == b"data":
                return bruto[pos + 8:pos + 8 + tamanho], taxa
            pos += 8 + tamanho + (tamanho % 2)
        raise TTSError("WAV sem bloco de dados")

    return bruto, taxa


def _chamar_modelo(
    falas: list[tuple[str, str]],
    vozes: dict[str, str],
    modelo: str,
    formato: str,
    timeout: int,
) -> tuple[bytes, int]:
    if not settings.GEMINI_API_KEY:
        raise TTSError("Chave do Gemini não configurada. Preencha GEMINI_API_KEY no arquivo .env")

    try:
        resp = httpx.post(
            GEMINI_URL.format(model=modelo),
            json=_payload(falas, vozes, formato),
            headers={
                "Content-Type": "application/json",
                "X-goog-api-key": settings.GEMINI_API_KEY,
            },
            timeout=timeout,
        )
    except httpx.RequestError as e:
        raise TTSError(f"Falha ao conectar no TTS do Gemini: {e}") from e

    if resp.status_code in _RETRY_STATUS:
        raise TTSError(f"{modelo} indisponível (status {resp.status_code})")
    if resp.status_code >= 400:
        # 400 aqui é quase sempre incompatibilidade de formato (ver o
        # cabeçalho deste arquivo) -- vale tentar o próximo modelo, que
        # fala o outro dialeto.
        raise TTSError(f"{modelo} recusou a requisição ({resp.status_code}): {resp.text[:200]}")

    try:
        dados = resp.json()
    except ValueError as e:
        raise TTSError(f"{modelo} devolveu resposta ilegível") from e

    return _extrair_pcm(dados)


def sintetizar(
    falas: list[tuple[str, str]],
    user_id: int,
    db,
    vozes: dict[str, str] | None = None,
    timeout: int = 45,
) -> tuple[bytes, int]:
    """Gera o áudio de um pedaço do roteiro. Devolve (pcm_16bit_mono, taxa).

    `falas` é [(locutor, texto), ...]. `vozes` mapeia locutor -> nome da
    voz; sem ele, o primeiro locutor a aparecer recebe a voz masculina e
    o segundo a feminina.

    Percorre TTS_MODELOS em ordem e devolve o primeiro que responder --
    cobre tanto o modelo fora do ar quanto o modelo que não entende o
    formato (as duas coisas aconteceram no teste real).
    """
    if not falas:
        raise TTSError("Roteiro vazio")

    segundos = estimar_segundos(falas)
    if segundos > MAX_SEGUNDOS_POR_PEDACO:
        raise TTSError(
            f"Pedaço longo demais para uma chamada: ~{segundos:.0f}s "
            f"(máximo {MAX_SEGUNDOS_POR_PEDACO}s). Divida o roteiro."
        )

    if vozes is None:
        locutores = list(dict.fromkeys(q for q, _ in falas))
        padrao = (VOZ_HOMEM, VOZ_MULHER)
        vozes = {q: padrao[i % 2] for i, q in enumerate(locutores)}

    # Debita ANTES de gerar, igual ao adaptador de texto: se estourou a
    # cota, não falamos com o provedor.
    if not check_and_consume_tokens(user_id, estimar_tokens_audio(falas), db):
        raise QuotaExceededError(
            "Limite diário de uso da IA atingido. Tente novamente amanhã."
        )

    inicio = time.monotonic()
    erros: list[str] = []
    for modelo, formato in TTS_MODELOS:
        restante = timeout - (time.monotonic() - inicio)
        if restante < 5:
            break
        try:
            pcm, taxa = _chamar_modelo(falas, vozes, modelo, formato, int(restante))
            if len(pcm) > BYTES_MAX_RESPOSTA:
                # Não dá pra devolver: a função serverless corta o corpo
                # e o cliente recebe áudio truncado, que é pior que um
                # erro. Avisa alto -- significa que CHARS_POR_SEGUNDO
                # desencostou da realidade e o roteiro precisa picar mais.
                sentry_sdk.capture_message(
                    f"TTS: pedaço acima do limite de resposta "
                    f"({len(pcm)} bytes, {len(pcm)/BYTES_POR_SEGUNDO:.0f}s)",
                    level="error",
                )
                raise TTSError(
                    f"Pedaço gerou {len(pcm)/BYTES_POR_SEGUNDO:.0f}s de áudio, "
                    "acima do que cabe numa resposta."
                )
            return pcm, taxa
        except TTSError as e:
            erros.append(str(e))
            print(f"[tts_failover] modelo={modelo} formato={formato} erro={e!r}")
            continue

    sentry_sdk.capture_message(f"TTS: todos os modelos falharam -- {erros}", level="error")
    raise TTSError("Nenhum modelo de TTS respondeu. " + " | ".join(erros))
