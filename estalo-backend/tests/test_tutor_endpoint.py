"""
Testes do Tutor Inteligente (POST /study/cards/{card_id}/tutor) — Gemini
mockado, sem rede (mesmo motivo/técnica de test_ai_mocked.py: httpx, não
`requests`, então o mock entra em app.services.ai.httpx.post).

Cobre: resposta em markdown, persistência em Card.tutor_explanation,
cache (segunda chamada não bate no Gemini de novo), erro da IA -> 503,
e isolamento entre usuários (card de outro usuário -> 404).
"""
from unittest.mock import Mock, patch

from app.core.config import settings


def _autenticar(client, email="tutor_test@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha123"})
    login = client.post("/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _resposta_gemini_mock(texto="**Paris** é a capital da França."):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    resp.raise_for_status.return_value = None
    return resp


def _criar_card(client, auth, front="Qual é a capital da França?", back="Paris"):
    deck = client.post("/decks", json={"title": "Deck Tutor"}, headers=auth).json()
    card = client.post(f"/decks/{deck['id']}/cards", json={"front": front, "back": back}, headers=auth).json()
    return card


def test_tutor_retorna_explicacao_e_persiste(client):
    auth = _autenticar(client)
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()) as mock_post:
        resp = client.post(f"/study/cards/{card['id']}/tutor", headers=auth)

    assert resp.status_code == 200
    assert resp.json()["explanation"] == "**Paris** é a capital da França."
    assert mock_post.called

    # Confirma a persistência (Card.tutor_explanation) sem chamar o Gemini
    # de novo -- se não tivesse persistido, este segundo POST tentaria
    # gerar de novo e o teste quebraria (nenhum mock ativo aqui).
    resp2 = client.post(f"/study/cards/{card['id']}/tutor", headers=auth)
    assert resp2.status_code == 200
    assert resp2.json()["explanation"] == "**Paris** é a capital da França."


def test_tutor_usa_cache_na_segunda_chamada(client):
    """Segunda chamada pro mesmo card não deve chamar o Gemini de novo --
    Card.tutor_explanation já teria sido preenchido na primeira."""
    auth = _autenticar(client, "tutor_cache@estalo.dev")
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()) as mock_post:
        primeira = client.post(f"/study/cards/{card['id']}/tutor", headers=auth)
    assert mock_post.call_count == 1

    with patch("app.services.ai.httpx.post") as mock_post_2:
        segunda = client.post(f"/study/cards/{card['id']}/tutor", headers=auth)

    assert not mock_post_2.called
    assert segunda.json()["explanation"] == primeira.json()["explanation"]


def test_tutor_erro_da_ia_retorna_503_amigavel(client):
    auth = _autenticar(client, "tutor_erro@estalo.dev")
    card = _criar_card(client, auth)

    resp_erro = Mock()
    resp_erro.status_code = 503
    resp_erro.raise_for_status.side_effect = Exception("indisponível")

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=resp_erro):
        resp = client.post(f"/study/cards/{card['id']}/tutor", headers=auth)

    assert resp.status_code == 503
    assert "Tutor indisponível" in resp.json()["detail"]


def test_tutor_card_de_outro_usuario_retorna_404(client):
    dono = _autenticar(client, "tutor_dono@estalo.dev")
    card = _criar_card(client, dono)

    intruso = _autenticar(client, "tutor_intruso@estalo.dev")
    resp = client.post(f"/study/cards/{card['id']}/tutor", headers=intruso)

    assert resp.status_code == 404
