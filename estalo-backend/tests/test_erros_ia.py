"""
O que o usuário lê quando a IA falha.

Seis endpoints devolviam `str(e)` do IAError como `detail` -- texto de
desenvolvedor ("A IA não devolveu um JSON válido", "Gemini indisponível
após 2 tentativas (...)", "Preencha GEMINI_API_KEY no arquivo .env")
que a tela mostrava inteiro pra quem tinha acabado de colar as
anotações. Agora todos passam por app/core/erros_ia.py: uma frase calma
no detail, o detalhe técnico no log. A cota estourada continua sendo
429 com a mensagem própria dela, porque o frontend abre um modal
específico pra isso.

Gemini mockado, sem rede (mesma técnica de test_tutor_endpoint.py).
"""
from unittest.mock import Mock, patch

from app.core.config import settings
from app.core.erros_ia import MENSAGEM_IA_INDISPONIVEL

# Palavras que só fazem sentido pra quem desenvolve o app. Nenhuma pode
# aparecer no que o usuário lê.
JARGAO = ("Gemini", "OpenAI", "JSON", "tentativas", ".env", "GEMINI_API_KEY", "httpx")


def _autenticar(client, email):
    client.post("/auth/register", json={"email": email, "password": "senha-de-teste-2026"})
    login = client.post("/auth/login", data={"username": email, "password": "senha-de-teste-2026"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _deck_com_card(client, auth):
    deck = client.post("/decks", json={"title": "Deck IA"}, headers=auth).json()
    card = client.post(f"/decks/{deck['id']}/cards", json={"front": "Pergunta", "back": "Resposta"}, headers=auth).json()
    return deck, card


def _gemini_fora():
    """Simula o Gemini respondendo 503 nas duas tentativas -- antes isso
    virava "Gemini indisponível após 2 tentativas (...)" na tela."""
    resp = Mock()
    resp.status_code = 503
    resp.raise_for_status.side_effect = Exception("Service Unavailable")
    return resp


def _gemini_respondendo_lixo():
    """Simula o Gemini devolvendo texto que não é JSON -- antes isso
    virava "A IA não devolveu um JSON válido" na tela."""
    resp = Mock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "isso não é json {"}]}}]}
    return resp


def _sem_jargao(detail: str):
    for palavra in JARGAO:
        assert palavra not in detail, f"'{palavra}' vazou pro usuário: {detail!r}"


def _chamadas_de_ia(client, auth, deck, card):
    """As seis chamadas que vazavam str(e). Cada uma é uma função que
    devolve a Response, pra rodar dentro do patch."""
    return {
        "gerar_cards": lambda: client.post(
            f"/decks/{deck['id']}/cards/generate", json={"text": "Um texto de estudo com mais de dez letras.", "quantity": 2}, headers=auth),
        "tutor_explain": lambda: client.post(
            f"/cards/{card['id']}/tutor", json={"action": "explain"}, headers=auth),
        "tutor_analyze": lambda: client.post(
            f"/cards/{card['id']}/tutor", json={"action": "analyze", "user_attempt": "achei que era outra coisa"}, headers=auth),
        "enrich": lambda: client.post(
            "/study/cards/enrich", json={"card_ids": [card["id"]]}, headers=auth),
        "quiz": lambda: client.post(f"/study/decks/{deck['id']}/quiz", headers=auth),
        "reveal": lambda: client.post(f"/study/decks/{deck['id']}/reveal", headers=auth),
    }


def test_ia_fora_do_ar_vira_uma_frase_calma_em_todos_os_endpoints(client):
    auth = _autenticar(client, "ia_fora@estalo.dev")
    deck, card = _deck_com_card(client, auth)

    for nome, chamar in _chamadas_de_ia(client, auth, deck, card).items():
        with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
             patch("app.services.ai.httpx.post", return_value=_gemini_fora()):
            resp = chamar()
        assert resp.status_code == 503, f"{nome}: {resp.status_code} {resp.text}"
        assert resp.json()["detail"] == MENSAGEM_IA_INDISPONIVEL, nome
        _sem_jargao(resp.json()["detail"])


def test_resposta_invalida_da_ia_tambem_nao_vaza_jargao(client):
    # O caso que mais aparecia na tela: "A IA não devolveu um JSON válido".
    auth = _autenticar(client, "ia_lixo@estalo.dev")
    deck, card = _deck_com_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=_gemini_respondendo_lixo()):
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": "Um texto de estudo com mais de dez letras.", "quantity": 2}, headers=auth)

    assert resp.status_code == 503
    assert resp.json()["detail"] == MENSAGEM_IA_INDISPONIVEL


def test_chave_nao_configurada_nao_vaza_instrucao_de_env(client):
    # "Chave do Gemini não configurada. Preencha GEMINI_API_KEY no arquivo
    # .env" é instrução pra quem faz deploy, não pra quem estuda.
    auth = _autenticar(client, "ia_sem_chave@estalo.dev")
    deck, _ = _deck_com_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", ""):
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": "Um texto de estudo com mais de dez letras.", "quantity": 2}, headers=auth)

    assert resp.status_code == 503
    _sem_jargao(resp.json()["detail"])


def test_cota_estourada_continua_429_com_a_mensagem_propria(client):
    # O frontend abre o modal de cota pelo 429 -- os endpoints de quiz e
    # enrich devolviam 502 nesse caso (o except IAError genérico engolia a
    # subclasse), e o modal nunca abria lá.
    auth = _autenticar(client, "ia_cota@estalo.dev")
    deck, card = _deck_com_card(client, auth)

    for nome, chamar in _chamadas_de_ia(client, auth, deck, card).items():
        with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
             patch("app.services.ai.check_and_consume_tokens", return_value=False):
            resp = chamar()
        assert resp.status_code == 429, f"{nome}: {resp.status_code} {resp.text}"
        assert "amanhã" in resp.json()["detail"], nome


def test_o_detalhe_tecnico_vai_pro_log(client, capsys):
    auth = _autenticar(client, "ia_log@estalo.dev")
    deck, _ = _deck_com_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=_gemini_fora()):
        client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": "Um texto de estudo com mais de dez letras.", "quantity": 2}, headers=auth)

    saida = capsys.readouterr().out
    assert "[ia_indisponivel] contexto=gerar_cards" in saida
    assert "Gemini" in saida  # o que sumiu da tela continua aqui
