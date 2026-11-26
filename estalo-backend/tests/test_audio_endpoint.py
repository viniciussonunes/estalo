"""
Endpoints da tela "Ouvir" (/decks/{id}/audio).

As regras que estes testes seguram, e o porquê de cada uma:

  - **Roteiro existente não é reescrito sozinho.** Reescrever gastaria a
    cota de IA da pessoa sem ela pedir. Só `?refazer=true` regrava, e
    quem decide é a tela -- que mostra o aviso de atrasado e o botão.
  - **"Atrasado" é calculado, não guardado.** O retrato dos cards
    (content_hash) é comparado na hora da leitura; guardar um booleano
    significaria lembrar de invalidá-lo em todo lugar que mexe em card,
    e algum lugar ficaria esquecido.
  - **Reordenar cards não atrasa o áudio.** O hash é ordenado: o que
    muda o que precisa ser dito é texto entrando, saindo ou mudando --
    não a ordem da lista.
  - **O áudio volta como bytes crus.** PCM em base64 dentro de JSON
    estouraria o limite de resposta da função serverless.
  - **Deck dos outros não existe.** 404, não 403 -- não confirma nem a
    existência do deck alheio.

A IA é mockada em todos: a suíte não fala com a rede.
"""
from unittest.mock import patch

ROTEIRO_FALSO = [
    {"titulo": "Abertura do assunto", "falas": [
        {"quem": "Rafael", "texto": "Explica isso pra mim?"},
        {"quem": "Beatriz", "texto": "Claro, funciona assim."}]},
    {"titulo": "Indo mais fundo", "falas": [
        {"quem": "Rafael", "texto": "E no caso difícil?"},
        {"quem": "Beatriz", "texto": "Aí muda, e o motivo é este."}]},
]

PCM_FALSO = b"\x00\x01" * 2000


def _autenticar(client, email):
    client.post("/auth/register", json={"email": email, "password": "senha-de-teste-2026"})
    login = client.post("/auth/login", data={"username": email, "password": "senha-de-teste-2026"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _deck_com_cards(client, auth, titulo="Farmacologia", quantos=4):
    deck = client.post("/decks", json={"title": titulo}, headers=auth).json()
    for i in range(quantos):
        client.post(f"/decks/{deck['id']}/cards",
                    json={"front": f"Pergunta {i}", "back": f"Resposta {i}"}, headers=auth)
    return deck


def _com_ia(roteiro=None):
    return patch("app.routers.audio.gerar_roteiro", return_value=roteiro or ROTEIRO_FALSO)


def _com_tts():
    return patch("app.routers.audio.sintetizar_bloco", return_value=(PCM_FALSO, 24000))


# ----------------------------------------------------------------- ver

def test_deck_sem_roteiro_responde_que_nao_existe(client):
    """"Não existe" é uma resposta, não um erro -- a tela precisa dela
    pra desenhar o estado vazio."""
    auth = _autenticar(client, "sem@estalo.dev")
    deck = _deck_com_cards(client, auth)
    r = client.get(f"/decks/{deck['id']}/audio", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"existe": False}


def test_deck_de_outro_usuario_nao_existe(client):
    dono = _autenticar(client, "dono@estalo.dev")
    deck = _deck_com_cards(client, dono)
    intruso = _autenticar(client, "intruso@estalo.dev")
    assert client.get(f"/decks/{deck['id']}/audio", headers=intruso).status_code == 404


# ------------------------------------------------------------- roteiro

def test_criar_roteiro_devolve_capitulos(client):
    auth = _autenticar(client, "cria@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["existe"] is True
    assert corpo["desatualizado"] is False
    assert corpo["total_blocos"] == 2
    assert [c["titulo"] for c in corpo["capitulos"]] == ["Abertura do assunto", "Indo mais fundo"]
    assert corpo["capitulos"][0]["indice"] == 0


def test_deck_vazio_nao_gera_roteiro(client):
    auth = _autenticar(client, "vazio@estalo.dev")
    deck = client.post("/decks", json={"title": "Sem cards"}, headers=auth).json()
    with _com_ia() as ia:
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert r.status_code == 400
    ia.assert_not_called()


def test_segunda_chamada_nao_gasta_ia_de_novo(client):
    """O custo de reescrever é da pessoa; ninguém pediu."""
    auth = _autenticar(client, "reusa@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    with _com_ia() as ia:
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert r.status_code == 201
    ia.assert_not_called()


def test_refazer_reescreve_e_substitui(client):
    auth = _autenticar(client, "refaz@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)

    outro = [{"titulo": "Versão nova", "falas": [{"quem": "Rafael", "texto": "oi"}]}]
    with _com_ia(outro) as ia:
        r = client.post(f"/decks/{deck['id']}/audio/roteiro?refazer=true", headers=auth)
    ia.assert_called_once()
    assert r.json()["total_blocos"] == 1
    assert r.json()["capitulos"][0]["titulo"] == "Versão nova"


def test_ia_fora_do_ar_vira_503_sem_jargao(client):
    from app.services.ai import IAError
    auth = _autenticar(client, "fora@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with patch("app.routers.audio.gerar_roteiro", side_effect=IAError("Gemini indisponível após 2 tentativas")):
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert r.status_code == 503
    assert "Gemini" not in r.json()["detail"]


def test_cota_estourada_vira_429(client):
    from app.services.ai import QuotaExceededError
    auth = _autenticar(client, "cota@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with patch("app.routers.audio.gerar_roteiro",
               side_effect=QuotaExceededError("Limite diário de uso da IA atingido.")):
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert r.status_code == 429
    assert "Limite diário" in r.json()["detail"]


# --------------------------------------------------------- atrasado

def test_mudar_um_card_marca_o_audio_como_atrasado(client):
    auth = _autenticar(client, "mudou@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert client.get(f"/decks/{deck['id']}/audio", headers=auth).json()["desatualizado"] is False

    cards = client.get(f"/decks/{deck['id']}/cards", headers=auth).json()
    alterado = client.patch(f"/cards/{cards[0]['id']}",
                            json={"front": "Pergunta mudada", "back": "Resposta mudada"},
                            headers=auth)
    assert alterado.status_code == 200, alterado.text

    assert client.get(f"/decks/{deck['id']}/audio", headers=auth).json()["desatualizado"] is True


def test_card_novo_marca_como_atrasado(client):
    auth = _autenticar(client, "novo@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    client.post(f"/decks/{deck['id']}/cards",
                json={"front": "Pergunta extra", "back": "Resposta extra"}, headers=auth)
    assert client.get(f"/decks/{deck['id']}/audio", headers=auth).json()["desatualizado"] is True


def test_hash_do_deck_ignora_a_ordem_dos_cards():
    """Reordenar não muda o que o áudio precisa dizer."""
    from app.models.deck_audio import calcular_hash_do_deck
    a = [("p1", "r1"), ("p2", "r2"), ("p3", "r3")]
    assert calcular_hash_do_deck(a) == calcular_hash_do_deck(list(reversed(a)))
    assert calcular_hash_do_deck(a) != calcular_hash_do_deck(a[:2])


# ------------------------------------------------------------- bloco

def test_bloco_volta_como_bytes_crus(client):
    """Base64 dentro de JSON estouraria o limite de resposta da função."""
    auth = _autenticar(client, "bloco@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    with _com_tts() as tts:
        r = client.post(f"/decks/{deck['id']}/audio/bloco/1", headers=auth)

    assert r.status_code == 200
    assert r.content == PCM_FALSO
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-taxa-amostragem"] == "24000"
    # Gravou o bloco 1, não o 0
    assert tts.call_args.args[0] == [{"quem": "Rafael", "texto": "E no caso difícil?"},
                                     {"quem": "Beatriz", "texto": "Aí muda, e o motivo é este."}]


def test_taxa_de_amostragem_chega_ao_javascript_do_navegador(client):
    """O cabeçalho só existe se o CORS deixar o JavaScript LÊ-LO.

    Sem expose_headers, o navegador recebe a resposta inteira mas esconde
    do script qualquer cabeçalho fora da lista segura do CORS: o
    `headers.get("X-Taxa-Amostragem")` do audioDecks.js devolvia null e o
    cliente caía sempre no padrão de 24 kHz, calado. Um modelo de TTS de
    48 kHz na lista de failover faria o MP3 ser codificado errado e tocar
    na metade da velocidade.

    Este teste tem que ser aqui, no backend: o e2e NÃO pega. As respostas
    fabricadas pelo route.fulfill do Playwright não passam pela checagem
    de CORS do navegador, então lá o cabeçalho sempre chega.
    """
    auth = _autenticar(client, "cors@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    with _com_tts():
        r = client.post(
            f"/decks/{deck['id']}/audio/bloco/0",
            headers={**auth, "Origin": "http://localhost:5173"},
        )

    assert r.status_code == 200
    expostos = {
        h.strip().lower()
        for h in r.headers.get("access-control-expose-headers", "").split(",")
    }
    assert "x-taxa-amostragem" in expostos, (
        "o cabeçalho da taxa não está em expose_headers -- o navegador vai "
        "esconder ele do JavaScript e o áudio será codificado na taxa errada"
    )


def test_bloco_fora_da_faixa_e_404(client):
    auth = _autenticar(client, "faixa@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    with _com_tts() as tts:
        assert client.post(f"/decks/{deck['id']}/audio/bloco/9", headers=auth).status_code == 404
        assert client.post(f"/decks/{deck['id']}/audio/bloco/-1", headers=auth).status_code == 404
    tts.assert_not_called()


def test_bloco_sem_roteiro_e_404(client):
    auth = _autenticar(client, "semroteiro@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_tts() as tts:
        assert client.post(f"/decks/{deck['id']}/audio/bloco/0", headers=auth).status_code == 404
    tts.assert_not_called()


# ------------------------------------------------------------ apagar

def test_apagar_esquece_o_roteiro(client):
    auth = _autenticar(client, "apaga@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert client.delete(f"/decks/{deck['id']}/audio", headers=auth).status_code == 204
    assert client.get(f"/decks/{deck['id']}/audio", headers=auth).json() == {"existe": False}


# ------------------------------------------------------- fase 2

def test_roteiro_recebe_alternativas_e_explicacao_dos_cards(client, db_session):
    """O erro do Rafael sai das alternativas erradas do card, e o porquê
    da Beatriz sai da explicação -- então elas têm que chegar à IA."""
    from app.models import Card

    auth = _autenticar(client, "material@estalo.dev")
    deck = _deck_com_cards(client, auth, quantos=2)
    db = db_session
    card = db.query(Card).filter(Card.deck_id == deck["id"]).order_by(Card.id).first()
    card.options = ["errada 1", "errada 2", "errada 3"]
    card.explanation = "o porquê"
    db.commit()

    with _com_ia() as ia:
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)

    cards = ia.call_args.args[1]
    assert cards[0]["distractors"] == ["errada 1", "errada 2", "errada 3"]
    assert cards[0]["explanation"] == "o porquê"
    # Card sem quiz ainda: listas vazias, não None
    assert cards[1]["distractors"] == [] and cards[1]["explanation"] == ""


def test_bloco_grava_com_as_vozes_fixas(client):
    from app.services.roteiro_audio import VOZES
    auth = _autenticar(client, "vozes@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia():
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    with _com_tts() as tts:
        client.post(f"/decks/{deck['id']}/audio/bloco/0", headers=auth)
    assert tts.call_args.kwargs["vozes"] == VOZES


def test_capitulo_conta_a_pausa_no_tamanho(client):
    """A tela posiciona os capítulos na barra pela proporção de
    caracteres; 3s de silêncio são tempo e precisam contar."""
    from app.services.roteiro_audio import CHARS_DA_PAUSA
    roteiro = [{"titulo": "Com pausa", "falas": [
        {"quem": "Beatriz", "texto": "abc"},
        {"quem": "Rafael", "texto": "de", "pausa": True},
        {"quem": "Beatriz", "texto": "f"}]}]
    auth = _autenticar(client, "capitulo@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia(roteiro):
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    assert r.json()["capitulos"][0]["caracteres"] == 6 + CHARS_DA_PAUSA


def test_pedaco_cortado_nao_vira_capitulo_novo(client):
    """Um bloco longo cortado em dois é UM capítulo pra quem ouve. A tela
    continua buscando os dois blocos de áudio (total_blocos)."""
    roteiro = [
        {"titulo": "Resolvedor", "falas": [{"quem": "Rafael", "texto": "aaaa"}]},
        {"titulo": "Resolvedor", "continua": True, "falas": [{"quem": "Beatriz", "texto": "bb"}]},
        {"titulo": "TTL", "falas": [{"quem": "Rafael", "texto": "c"}]},
    ]
    auth = _autenticar(client, "capitulos@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia(roteiro):
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth).json()
    assert r["total_blocos"] == 3
    assert r["capitulos"] == [
        {"indice": 0, "titulo": "Resolvedor", "caracteres": 6},
        {"indice": 2, "titulo": "TTL", "caracteres": 1}]


def test_roteiro_da_fase_1_com_sufixo_tambem_agrupa(client):
    roteiro = [
        {"titulo": "Penicilinas", "falas": [{"quem": "Rafael", "texto": "aa"}]},
        {"titulo": "Penicilinas (continuação)", "falas": [{"quem": "Beatriz", "texto": "bbb"}]},
    ]
    auth = _autenticar(client, "fase1@estalo.dev")
    deck = _deck_com_cards(client, auth)
    with _com_ia(roteiro):
        r = client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth).json()
    assert r["capitulos"] == [{"indice": 0, "titulo": "Penicilinas", "caracteres": 5}]
