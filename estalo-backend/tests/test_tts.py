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
    return [{"quem": (QUEM_PERGUNTA if i % 2 == 0 else QUEM_EXPLICA), "texto": "x" * tam}
            for i in range(quantas)]


def test_bloco_dentro_do_limite_nao_e_cortado():
    falas = _falas_de(CHARS_MAX_POR_BLOCO - 100)
    assert _dividir_bloco_longo(falas) == [falas]


def test_bloco_longo_vira_pedacos_parecidos_sem_rabo():
    """O bug que isto trava: 889 chars viravam 690 + 199, e os 199
    apareciam como um capítulo de 11 segundos."""
    falas = _falas_de(int(CHARS_MAX_POR_BLOCO * 1.3), quantas=12)
    pedacos = _dividir_bloco_longo(falas)

    assert len(pedacos) == 2
    tamanhos = [sum(len(f["texto"]) for f in p) for p in pedacos]
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


def test_validar_marca_o_pedaco_cortado_como_continuacao():
    falas = [{"quem": QUEM_PERGUNTA if i % 2 == 0 else QUEM_EXPLICA,
              "texto": "y" * 150} for i in range(12)]
    blocos = _validar({"blocos": [{"titulo": "Mecanismo de ação", "falas": falas}]})
    assert len(blocos) > 1
    assert all(b["titulo"] == "Mecanismo de ação" for b in blocos)
    assert "continua" not in blocos[0]
    assert all(b["continua"] is True for b in blocos[1:])


# ------------------------------------------- fase 2: pausa pra quem ouve
#
# A pergunta que Beatriz faz pra quem ouve, a fala de espera do Rafael, o
# silêncio e a resposta são um momento só. As regras abaixo garantem que
# o silêncio cai no lugar certo e que nada corta esse momento ao meio.

from app.services.roteiro_audio import (  # noqa: E402
    CHARS_DA_PAUSA,
    VOZES as VOZES_DO_ROTEIRO,
    _montar_prompt,
    tamanho_do_bloco,
)
from app.services.tts import PAUSA_PARA_PENSAR_S, sintetizar_bloco  # noqa: E402

R, B = QUEM_PERGUNTA, QUEM_EXPLICA


def _bloco(*falas):
    return {"blocos": [{"titulo": "Teste", "falas": list(falas)}]}


def test_falas_seguidas_da_mesma_pessoa_viram_uma():
    """Visto no protótipo: a IA põe Beatriz duas vezes seguidas mesmo
    proibida. No áudio, soa como corte de edição."""
    blocos = _validar(_bloco(
        {"quem": R, "texto": "E o MRSA?"},
        {"quem": B, "texto": "Tem PBP alterada."},
        {"quem": B, "texto": "Por isso vancomicina."}))
    assert blocos[0]["falas"] == [
        {"quem": R, "texto": "E o MRSA?"},
        {"quem": B, "texto": "Tem PBP alterada. Por isso vancomicina."}]


def test_pausa_cai_depois_da_fala_de_espera_do_rafael():
    """Pergunta -> "Hmm" -> silêncio -> resposta. Silêncio logo depois da
    pergunta soaria como áudio travado; o "Hmm" avisa que é de propósito."""
    blocos = _validar(_bloco(
        {"quem": B, "texto": "E você aí: por que o TTL baixa antes da migração?",
         "para_quem_ouve": True},
        {"quem": R, "texto": "Hmm... deixa eu pensar nessa."},
        {"quem": B, "texto": "Pra mudança se espalhar rápido."}))
    falas = blocos[0]["falas"]
    assert [f.get("pausa", False) for f in falas] == [False, True, False]
    assert all("para_quem_ouve" not in f for f in falas)


def test_sem_fala_de_espera_a_pausa_vai_logo_depois_da_pergunta():
    blocos = _validar(_bloco(
        {"quem": B, "texto": "E você aí: qual porta o DNS usa?", "para_quem_ouve": True},
        {"quem": R, "texto": "Cinquenta e três, e sobre UDP na maior parte do tempo, "
                             "porque as consultas são pequenas e precisam ser rápidas."}))
    assert [f.get("pausa", False) for f in blocos[0]["falas"]] == [True, False]


def test_pergunta_na_ultima_fala_nao_ganha_pausa():
    """Sem resposta depois, a pausa seria silêncio no fim do capítulo."""
    blocos = _validar(_bloco(
        {"quem": R, "texto": "E os carbapenêmicos?"},
        {"quem": B, "texto": "E você aí: por que são reservados?", "para_quem_ouve": True}))
    assert not any(f.get("pausa") for f in blocos[0]["falas"])


def test_marcacao_que_nao_e_true_e_ignorada():
    blocos = _validar(_bloco(
        {"quem": B, "texto": "Pergunta?", "para_quem_ouve": "sim"},
        {"quem": R, "texto": "Acho que é a parede."},
        {"quem": B, "texto": "Resposta."}))
    assert not any(f.get("pausa") for f in blocos[0]["falas"])


def test_pausa_conta_no_tamanho_do_bloco():
    falas = [{"quem": R, "texto": "abc", "pausa": True}, {"quem": B, "texto": "de"}]
    assert tamanho_do_bloco(falas) == 5 + CHARS_DA_PAUSA


def test_corte_de_bloco_longo_nao_separa_pergunta_de_resposta():
    """Montado pra o corte igual cair exatamente entre a fala de espera e
    a resposta: as duas primeiras falas ficam logo abaixo do alvo, e a
    pergunta + espera + pausa o ultrapassam. Sem a regra, o capítulo novo
    começaria pela resposta, sem a pergunta."""
    q = int(CHARS_MAX_POR_BLOCO * 0.35)
    falas = [
        {"quem": R, "texto": "a" * q},
        {"quem": B, "texto": "b" * q},
        {"quem": B, "texto": "p" * 40, "para_quem_ouve": True},
        {"quem": R, "texto": "h" * 20, "pausa": True},
        {"quem": B, "texto": "r" * q},
        {"quem": R, "texto": "z" * q},
    ]
    pedacos = _dividir_bloco_longo(falas)

    assert len(pedacos) == 2
    assert [f["texto"][0] for f in pedacos[1]][:3] == ["p", "h", "r"], (
        "pergunta, espera e resposta têm que ficar no mesmo capítulo")
    assert all(tamanho_do_bloco(p) <= CHARS_MAX_POR_BLOCO for p in pedacos)


def test_prompt_leva_alternativas_erradas_e_explicacao():
    """É o material do erro do Rafael e do porquê da Beatriz."""
    prompt = _montar_prompt("Redes", [{
        "front": "Porta do DNS?", "back": "53",
        "distractors": ["80", "443", "22"], "explanation": "Consultas pequenas, via UDP."}], 3)
    assert '"confusoes_comuns"' in prompt and '"443"' in prompt
    assert "Consultas pequenas, via UDP." in prompt
    assert "para_quem_ouve" in prompt


def test_prompt_aceita_card_sem_alternativas():
    """Card manual, sem quiz gerado ainda: não pode quebrar o roteiro."""
    prompt = _montar_prompt("Redes", [{"front": "Porta do DNS?", "back": "53"}], 3)
    assert '"confusoes_comuns": []' in prompt


def test_vozes_do_roteiro_sao_fixas_por_pessoa():
    """O bug da fase 1: sem vozes explícitas, quem falava primeiro no
    bloco levava a voz masculina -- Beatriz abrindo um bloco saía com a
    voz do Rafael."""
    assert VOZES_DO_ROTEIRO == {QUEM_PERGUNTA: tts.VOZ_HOMEM, QUEM_EXPLICA: tts.VOZ_MULHER}


def test_bloco_com_pausa_emenda_silencio_de_verdade():
    falas = [
        {"quem": B, "texto": "E você aí: por quê?"},
        {"quem": R, "texto": "Hmm.", "pausa": True},
        {"quem": B, "texto": "Porque sim."},
    ]
    partes = [(b"\x01\x02" * 10, 24000), (b"\x03\x04" * 7, 24000)]
    with patch("app.services.tts.sintetizar", side_effect=partes) as sint:
        pcm, taxa = sintetizar_bloco(falas, user_id=1, db=None, vozes=VOZES_DO_ROTEIRO)

    silencio = b"\x00\x00" * int(PAUSA_PARA_PENSAR_S * 24000)
    assert pcm == b"\x01\x02" * 10 + silencio + b"\x03\x04" * 7
    assert taxa == 24000
    assert [c.args[0] for c in sint.call_args_list] == [
        [(B, "E você aí: por quê?"), (R, "Hmm.")], [(B, "Porque sim.")]]
    # A mesma pessoa tem a mesma voz nos dois trechos.
    assert all(c.kwargs["vozes"] == VOZES_DO_ROTEIRO for c in sint.call_args_list)


def test_bloco_sem_pausa_e_uma_chamada_so():
    falas = [{"quem": R, "texto": "Oi."}, {"quem": B, "texto": "Olá."}]
    with patch("app.services.tts.sintetizar", return_value=(b"\x05\x06", 24000)) as sint:
        pcm, _ = sintetizar_bloco(falas, user_id=1, db=None, vozes=VOZES_DO_ROTEIRO)
    assert sint.call_count == 1 and pcm == b"\x05\x06"


def test_trechos_com_taxas_diferentes_falham_em_vez_de_tocar_errado():
    """O failover pode trocar de modelo no meio do bloco; emendar taxas
    diferentes faria um trecho tocar na velocidade errada."""
    falas = [{"quem": B, "texto": "Pergunta?", "pausa": True}, {"quem": R, "texto": "Resposta."}]
    with patch("app.services.tts.sintetizar", side_effect=[(b"\x00\x00", 24000), (b"\x00\x00", 48000)]):
        with pytest.raises(TTSError):
            sintetizar_bloco(falas, user_id=1, db=None, vozes=VOZES_DO_ROTEIRO)


def test_carimbo_de_concordancia_sai_do_comeco_da_fala():
    blocos = _validar(_bloco(
        {"quem": R, "texto": "Certo, vamos revisar os betalactâmicos."},
        {"quem": B, "texto": "Exatamente. o anel define a classe."},
        {"quem": R, "texto": "Isso mesmo! E o alvo?"},
        {"quem": B, "texto": "Perfeito, as PBPs."}))
    assert [f["texto"] for f in blocos[0]["falas"]] == [
        "Vamos revisar os betalactâmicos.", "O anel define a classe.", "E o alvo?", "As PBPs."]


def test_carimbo_sozinho_fica_e_palavra_parecida_nao_e_carimbo():
    """Uma fala que é SÓ "Certo." não vira fala vazia; e "Isso" seguido de
    conteúdo sem pontuação ("Isso inativa o antibiótico") é frase, não
    carimbo."""
    blocos = _validar(_bloco(
        {"quem": R, "texto": "Certo."},
        {"quem": B, "texto": "Isso inativa o antibiótico."}))
    assert [f["texto"] for f in blocos[0]["falas"]] == ["Certo.", "Isso inativa o antibiótico."]


def test_hesitacao_colada_na_resposta_e_separada_e_a_pausa_fica_no_meio():
    """Visto em teste real: "Hmm... deixa eu pensar. Eles são bactericidas
    porque..." numa fala só. A pausa caía antes do "Hmm"."""
    blocos = _validar(_bloco(
        {"quem": B, "texto": "E você aí: por que são bactericidas?", "para_quem_ouve": True},
        {"quem": R, "texto": "Hmm... deixa eu pensar nessa. Porque a parede rompe."},
        {"quem": B, "texto": "E rompe mais quando a bactéria cresce."}))
    falas = blocos[0]["falas"]
    assert [(f["texto"], f.get("pausa", False)) for f in falas] == [
        ("E você aí: por que são bactericidas?", False),
        ("Hmm... deixa eu pensar nessa.", True),
        ("Porque a parede rompe.", False),
        ("E rompe mais quando a bactéria cresce.", False)]


def test_nenhum_pedaco_passa_do_teto():
    """Visto em teste: o último pedaço juntava a sobra e chegava a 1134
    caracteres (~3,9 MB de PCM), encostado no limite de resposta."""
    import random
    rnd = random.Random(7)
    for _ in range(200):
        falas = []
        for i in range(rnd.randint(4, 24)):
            f = {"quem": R if i % 2 == 0 else B, "texto": "x" * rnd.randint(20, 260)}
            if rnd.random() < 0.15:
                f["para_quem_ouve"] = True
            falas.append(f)
        pedacos = _dividir_bloco_longo(falas)
        assert [f for p in pedacos for f in p] == falas, "fala perdida ou fora de ordem"
        for p in pedacos:
            if len(p) > 1:
                assert tamanho_do_bloco(p) <= CHARS_MAX_POR_BLOCO, [tamanho_do_bloco(x) for x in pedacos]


def test_trecho_acima_do_teto_de_uma_chamada_e_gravado_em_partes():
    """O bloco pode passar de 60s (teto de UMA chamada de voz) desde que
    seja gravado em partes. Corte entre falas, sem silêncio no meio."""
    longa = "x" * int(tts.CHARS_POR_SEGUNDO * 35)   # ~35s cada
    falas = [{"quem": R, "texto": longa}, {"quem": B, "texto": longa}]
    with patch("app.services.tts.sintetizar", side_effect=[(b"\x01\x00", 24000), (b"\x02\x00", 24000)]) as sint:
        pcm, _ = sintetizar_bloco(falas, user_id=1, db=None, vozes=VOZES_DO_ROTEIRO)
    assert sint.call_count == 2
    assert pcm == b"\x01\x00\x02\x00"


def test_bloco_no_teto_cabe_na_resposta_com_a_pausa():
    """O teto do bloco é escolhido pelo limite de resposta da função."""
    segundos = tts.MAX_SEGUNDOS_POR_BLOCO + PAUSA_PARA_PENSAR_S
    assert segundos * tts.BYTES_POR_SEGUNDO < tts.BYTES_MAX_RESPOSTA


def test_trecho_de_uma_pessoa_so_usa_o_modo_de_uma_voz():
    """O modo de duas vozes exige exatamente dois locutores: os três
    modelos respondem 400 com um só (visto no teste real). Trecho assim
    aparece quando a pausa corta o bloco."""
    falas = [(QUEM_EXPLICA, "Porque o alvo não existe em nós."), (QUEM_EXPLICA, "Simples.")]
    for formato in (FORMATO_FALAS, FORMATO_BLOCO):
        p = _payload(falas, VOZES, formato)
        cfg = p["generationConfig"]["speechConfig"]
        assert "multiSpeakerVoiceConfig" not in cfg
        assert cfg["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == VOZES[QUEM_EXPLICA]
        assert p["contents"][0]["parts"] == [{"text": "Porque o alvo não existe em nós. Simples."}]


def test_pergunta_pra_quem_ouve_sem_marca_e_reconhecida_pelo_texto():
    """Visto no teste real: a IA escreveu "Para quem está ouvindo: ...?" e
    "E você aí: ...?" sem a marca para_quem_ouve -- e o áudio saiu sem
    nenhuma pausa."""
    for pergunta in ("Para quem está ouvindo: por que essa restrição existe?",
                     "E você aí: por que são iterativas?"):
        blocos = _validar(_bloco(
            {"quem": B, "texto": pergunta},
            {"quem": R, "texto": "Hmm... deixa eu pensar nessa."},
            {"quem": B, "texto": "Porque cada um só indica o próximo."}))
        assert [f.get("pausa", False) for f in blocos[0]["falas"]] == [False, True, False], pergunta


def test_pergunta_seguida_de_hesitacao_e_pra_quem_ouve_mesmo_sem_chamado():
    blocos = _validar(_bloco(
        {"quem": B, "texto": "E por que o TTL baixa antes da migração?"},
        {"quem": R, "texto": "Hmm, deixa eu pensar."},
        {"quem": B, "texto": "Pra mudança se espalhar rápido."}))
    assert [f.get("pausa", False) for f in blocos[0]["falas"]] == [False, True, False]


def test_pergunta_da_beatriz_pro_rafael_nao_ganha_pausa():
    """Beatriz também devolve perguntas pro Rafael, e ele responde direto:
    isso é conversa, não vez de quem ouve."""
    blocos = _validar(_bloco(
        {"quem": B, "texto": "E qual porta o DNS usa?"},
        {"quem": R, "texto": "Cinquenta e três, sobre UDP."},
        {"quem": B, "texto": "E TCP quando a resposta é grande."}))
    assert not any(f.get("pausa") for f in blocos[0]["falas"])


def test_hmm_solto_nao_e_fala_de_espera():
    """Visto em teste: Beatriz perguntou PRO RAFAEL e ele respondeu "Hmm, a
    característica comum? Acho que..." -- o "Hmm," solto virou fala de
    espera e pôs 3s de silêncio no meio da frase dele."""
    blocos = _validar(_bloco(
        {"quem": B, "texto": "Você lembra qual é a característica comum?"},
        {"quem": R, "texto": "Hmm, a característica comum? Acho que é o núcleo peptídico."},
        {"quem": B, "texto": "Não: é o anel betalactâmico."}))
    falas = blocos[0]["falas"]
    assert len(falas) == 3
    assert not any(f.get("pausa") for f in falas)
