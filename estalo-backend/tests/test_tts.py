"""
Adaptador de TTS e roteirista de áudio (dois locutores).

O que estes testes seguram, e por que cada regra existe:

  - **Dois dialetos de API.** A mesma funcionalidade tem dois formatos de
    requisição no Gemini, e qual vale depende do modelo. Medido em
    2026-11-05: o 3.8 exige speechMetadata por fala e o 2.5 responde 400
    pra isso, exigindo o roteiro num texto só. Montar o payload errado
    pro modelo certo é a falha mais provável desta camada.
  - **Failover entre modelos.** No mesmo teste real, o 3.8 estava
    devolvendo 503 ("high demand") enquanto o 2.5 respondia. Sem reserva,
    a tela de Ouvir quebra quando o modelo mais novo tosse.
  - **Corte de bloco longo.** A IA estoura o tamanho pedido com
    frequência (medido: pedi 900 caracteres, veio 1138). Um bloco acima
    do teto não cabe na resposta da função serverless, então o código
    corta -- e corta em partes IGUAIS, porque encher-até-estourar deixava
    um capítulo órfão de 11 segundos chamado "(continuação)".
  - **Cota antes de gastar.** TTS custa dinheiro; nenhum caminho pode
    gerar áudio sem passar pelo medidor.

Tudo mockado no httpx, sem rede.
"""
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import tts
from app.services.ai import QuotaExceededError
from app.services.roteiro_audio import (
    CHARS_MAX_POR_BLOCO,
    QUEM_EXPLICA,
    QUEM_PERGUNTA,
    _dividir_bloco_longo,
    _validar,
)
from app.services.tts import (
    FORMATO_BLOCO,
    FORMATO_FALAS,
    TTSError,
    _payload,
    sintetizar,
)

FALAS = [(QUEM_PERGUNTA, "Por que a penicilina não nos mata?"),
         (QUEM_EXPLICA, "Porque o alvo dela só existe na bactéria.")]
VOZES = {QUEM_PERGUNTA: "Puck", QUEM_EXPLICA: "Kore"}


# --------------------------------------------------------------- payload

def test_formato_falas_marca_locutor_em_cada_parte():
    """O modelo novo recusa (400) se faltar speechMetadata em qualquer parte."""
    parts = _payload(FALAS, VOZES, FORMATO_FALAS)["contents"][0]["parts"]
    assert len(parts) == 2
    assert [p["speechMetadata"]["speaker"] for p in parts] == [QUEM_PERGUNTA, QUEM_EXPLICA]
    assert parts[0]["text"] == FALAS[0][1]


def test_formato_bloco_junta_tudo_num_texto_so():
    """O modelo 2.5 recusa speechMetadata e espera o roteiro prefixado."""
    parts = _payload(FALAS, VOZES, FORMATO_BLOCO)["contents"][0]["parts"]
    assert len(parts) == 1
    assert "speechMetadata" not in parts[0]
    texto = parts[0]["text"]
    assert texto.startswith(f"TTS the following conversation between {QUEM_PERGUNTA} and {QUEM_EXPLICA}:")
    assert f"{QUEM_PERGUNTA}: {FALAS[0][1]}" in texto


def test_vozes_vao_nos_dois_formatos():
    for formato in (FORMATO_FALAS, FORMATO_BLOCO):
        cfg = _payload(FALAS, VOZES, formato)["generationConfig"]
        vozes = cfg["speechConfig"]["multiSpeakerVoiceConfig"]["speakerVoiceConfigs"]
        assert {v["speaker"]: v["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] for v in vozes} == VOZES
        assert cfg["responseModalities"] == ["AUDIO"]


# -------------------------------------------------------------- failover

def _resposta(status, pcm=b"\x00\x01" * 1000):
    import base64

    class R:
        status_code = status
        text = "erro"

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [
                {"inlineData": {"data": base64.b64encode(pcm).decode(),
                                "mimeType": "audio/L16;rate=24000"}}]}}]}
    return R()


def test_modelo_sobrecarregado_cai_pro_proximo():
    """503 no modelo preferido não pode derrubar a geração."""
    chamados = []

    def falso_post(url, **kwargs):
        chamados.append(url)
        return _resposta(503) if len(chamados) == 1 else _resposta(200)

    with patch.object(settings, "GEMINI_API_KEY", "x"), \
         patch("app.services.tts.httpx.post", side_effect=falso_post), \
         patch("app.services.tts.check_and_consume_tokens", return_value=True):
        pcm, taxa = sintetizar(FALAS, user_id=1, db=None)

    assert len(chamados) == 2
    assert tts.TTS_MODELOS[0][0] in chamados[0]
    assert tts.TTS_MODELOS[1][0] in chamados[1]
    assert pcm and taxa == 24000


def test_modelo_que_recusa_o_formato_cai_pro_proximo():
    """400 "Speech metadata is not supported" é o outro dialeto, não o fim."""
    def falso_post(url, **kwargs):
        if tts.TTS_MODELOS[0][0] in url:
            return _resposta(400)
        return _resposta(200)

    with patch.object(settings, "GEMINI_API_KEY", "x"), \
         patch("app.services.tts.httpx.post", side_effect=falso_post), \
         patch("app.services.tts.check_and_consume_tokens", return_value=True):
        pcm, _ = sintetizar(FALAS, user_id=1, db=None)
    assert pcm


def test_todos_falhando_cita_os_modelos():
    with patch.object(settings, "GEMINI_API_KEY", "x"), \
         patch("app.services.tts.httpx.post", return_value=_resposta(503)), \
         patch("app.services.tts.check_and_consume_tokens", return_value=True), \
         patch("app.services.tts.sentry_sdk.capture_message"):
        with pytest.raises(TTSError) as e:
            sintetizar(FALAS, user_id=1, db=None)
    assert tts.TTS_MODELOS[0][0] in str(e.value)


# ------------------------------------------------------------------ cota

def test_cota_estourada_barra_antes_de_chamar_a_api():
    with patch.object(settings, "GEMINI_API_KEY", "x"), \
         patch("app.services.tts.check_and_consume_tokens", return_value=False), \
         patch("app.services.tts.httpx.post") as post:
        with pytest.raises(QuotaExceededError):
            sintetizar(FALAS, user_id=1, db=None)
    post.assert_not_called()


def test_pedaco_longo_demais_nem_tenta():
    """Guarda contra roteiro mal picado -- não cabe na resposta da função."""
    gigante = [(QUEM_PERGUNTA, "a" * 20000)]
    with patch.object(settings, "GEMINI_API_KEY", "x"), \
         patch("app.services.tts.httpx.post") as post, \
         patch("app.services.tts.check_and_consume_tokens", return_value=True):
        with pytest.raises(TTSError, match="longo demais"):
            sintetizar(gigante, user_id=1, db=None)
    post.assert_not_called()


# ------------------------------------------------------- extração do PCM

def test_wav_com_cabecalho_vira_pcm_cru():
    """A API às vezes embrulha em RIFF; o cabeçalho no meio de uma
    concatenação vira chiado audível."""
    import base64, struct
    pcm = b"\x01\x02" * 500
    wav = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
           + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
           + b"data" + struct.pack("<I", len(pcm)) + pcm)
    saida, taxa = tts._extrair_pcm({"candidates": [{"content": {"parts": [
        {"inlineData": {"data": base64.b64encode(wav).decode(), "mimeType": "audio/wav"}}]}}]})
    assert saida == pcm
    assert taxa == 24000


# ------------------------------------------------- corte de bloco longo

def _falas_de(total_chars, quantas=10):
    tam = total_chars // quantas
    return [((QUEM_PERGUNTA if i % 2 == 0 else QUEM_EXPLICA), "x" * tam) for i in range(quantas)]


def test_bloco_dentro_do_limite_nao_e_cortado():
    falas = _falas_de(CHARS_MAX_POR_BLOCO - 100)
    assert _dividir_bloco_longo(falas) == [falas]


def test_bloco_longo_vira_pedacos_parecidos_sem_rabo():
    """O bug que isto trava: 889 chars viravam 690 + 199, e os 199
    apareciam como um capítulo de 11 segundos."""
    falas = _falas_de(int(CHARS_MAX_POR_BLOCO * 1.3), quantas=12)
    pedacos = _dividir_bloco_longo(falas)

    assert len(pedacos) == 2
    tamanhos = [sum(len(t) for _, t in p) for p in pedacos]
    assert all(t <= CHARS_MAX_POR_BLOCO for t in tamanhos)
    menor, maior = min(tamanhos), max(tamanhos)
    assert menor / maior > 0.6, f"pedaços desequilibrados: {tamanhos}"


def test_nenhuma_fala_se_perde_no_corte():
    falas = _falas_de(int(CHARS_MAX_POR_BLOCO * 2.4), quantas=15)
    pedacos = _dividir_bloco_longo(falas)
    assert [f for p in pedacos for f in p] == falas


# ------------------------------------------------- validação do roteiro

def test_validar_aceita_locutor_com_caixa_diferente():
    blocos = _validar({"blocos": [{"titulo": "Abertura", "falas": [
        {"quem": QUEM_PERGUNTA.lower(), "texto": "oi"},
        {"quem": QUEM_EXPLICA.upper(), "texto": "olá"}]}]})
    assert [f["quem"] for f in blocos[0]["falas"]] == [QUEM_PERGUNTA, QUEM_EXPLICA]


def test_validar_descarta_locutor_inventado():
    blocos = _validar({"blocos": [{"titulo": "Abertura", "falas": [
        {"quem": "Narrador", "texto": "era uma vez"},
        {"quem": QUEM_EXPLICA, "texto": "isto fica"}]}]})
    assert [f["texto"] for f in blocos[0]["falas"]] == ["isto fica"]


def test_validar_explode_com_roteiro_vazio():
    from app.services.ai import IAError
    with pytest.raises(IAError):
        _validar({"blocos": []})
    with pytest.raises(IAError):
        _validar({"nada": 1})


def test_validar_marca_continuacao_no_bloco_cortado():
    falas = [{"quem": QUEM_PERGUNTA if i % 2 == 0 else QUEM_EXPLICA,
              "texto": "y" * 150} for i in range(12)]
    blocos = _validar({"blocos": [{"titulo": "Mecanismo de ação", "falas": falas}]})
    assert len(blocos) > 1
    assert blocos[0]["titulo"] == "Mecanismo de ação"
    assert "continuação" in blocos[1]["titulo"]
