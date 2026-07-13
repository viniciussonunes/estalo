"""
Testes da Leitura em Inglês (POST /decks/{id}/cards/generate com
language_level no corpo) -- Gemini mockado, sem rede (mesma técnica do
resto da suíte: httpx, não `requests`).

Cobre: geração feliz vira Card de verdade com source="ai_reading",
language_level ausente preserva o comportamento genérico de sempre
(source="ai", sem regressão), validação de texto grande demais (422 sem
chamar IA), CEFR/idioma inválidos (422), o prompt carregando nível e
idioma da resposta corretos, e erro de IA vira 502 (mesmo padrão do
gerar_cards_completos genérico).
"""
import json
from unittest.mock import Mock, patch

from app.core.config import settings
from app.models.card import Card


def _autenticar(client, email="leitura_test@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha123"})
    login = client.post("/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _criar_deck(client, auth, titulo="Deck Leitura"):
    return client.post("/decks", json={"title": titulo}, headers=auth).json()


def _resposta_gemini_mock(corpo: list[dict]):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(corpo)}]}}]}
    resp.raise_for_status.return_value = None
    return resp


_TEXTO_INGLES = (
    "The company's revenue increased dramatically last quarter, "
    "exceeding analysts' expectations."
)

_CARDS_LEITURA_VALIDOS = [
    {
        "front": "The company's revenue increased dramatically last quarter, "
                 "**exceeding** analysts' expectations.",
        "back": "indo além de, superando",
        "distractors": ["diminuindo", "igualando", "atrasando"],
        "explanation": "'Exceeding expectations' significa superar o que era esperado.",
    },
]


def test_leitura_ingles_gera_card_com_source_ai_reading(client, db_session):
    auth = _autenticar(client)
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_CARDS_LEITURA_VALIDOS)) as mock_post:
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": _TEXTO_INGLES, "quantity": 1, "language_level": "B1"},
            headers=auth,
        )

    assert resp.status_code == 201
    assert mock_post.called
    corpo = resp.json()
    assert len(corpo) == 1
    assert corpo[0]["source"] == "ai_reading"
    assert "exceeding" in corpo[0]["front"]
    assert corpo[0]["back"] == "indo além de, superando"
    assert len(corpo[0]["options"]) == 3

    salvo = db_session.query(Card).filter(Card.deck_id == deck["id"]).first()
    assert salvo.source == "ai_reading"


def test_sem_language_level_mantem_comportamento_generico_source_ai(client):
    """Guarda de regressão: omitir language_level continua gerando
    flashcard genérico como sempre, source="ai" -- o campo novo é
    aditivo, não muda o default."""
    auth = _autenticar(client, "generico@estalo.dev")
    deck = _criar_deck(client, auth)

    cards_genericos = [{
        "front": "O que é Zero Trust?",
        "back": "Nunca confie, sempre verifique",
        "distractors": ["a", "b", "c"],
        "explanation": "explicação",
    }]
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(cards_genericos)):
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": "Zero Trust é um modelo de segurança de TI.", "quantity": 1},
            headers=auth,
        )

    assert resp.status_code == 201
    assert resp.json()[0]["source"] == "ai"


def test_prompt_carrega_nivel_cefr_e_idioma_da_resposta(client):
    auth = _autenticar(client, "prompt_nivel@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_CARDS_LEITURA_VALIDOS)) as mock_post:
        client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": _TEXTO_INGLES, "quantity": 3, "language_level": "C1", "answer_language": "en"},
            headers=auth,
        )

    prompt_enviado = mock_post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "CEFR C1" in prompt_enviado
    assert "em inglês" in prompt_enviado
    assert "até 3 palavras" in prompt_enviado
    assert _TEXTO_INGLES in prompt_enviado


def test_answer_language_default_e_portugues(client):
    auth = _autenticar(client, "idioma_default@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_CARDS_LEITURA_VALIDOS)) as mock_post:
        client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": _TEXTO_INGLES, "quantity": 1, "language_level": "B1"},
            headers=auth,
        )

    prompt_enviado = mock_post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "em português" in prompt_enviado


def test_texto_maior_que_12000_chars_da_422_sem_chamar_ia(client):
    auth = _autenticar(client, "texto_grande@estalo.dev")
    deck = _criar_deck(client, auth)

    texto_gigante = "a" * 12_001
    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": texto_gigante, "quantity": 1, "language_level": "B1"},
            headers=auth,
        )

    assert resp.status_code == 422
    assert not mock_post.called


def test_texto_no_limite_de_12000_chars_e_aceito(client):
    auth = _autenticar(client, "texto_limite@estalo.dev")
    deck = _criar_deck(client, auth)

    texto_no_limite = _TEXTO_INGLES + "a" * (12_000 - len(_TEXTO_INGLES))
    assert len(texto_no_limite) == 12_000

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_CARDS_LEITURA_VALIDOS)):
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": texto_no_limite, "quantity": 1, "language_level": "B1"},
            headers=auth,
        )

    assert resp.status_code == 201


def test_language_level_invalido_da_422_sem_chamar_ia(client):
    auth = _autenticar(client, "nivel_invalido@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": _TEXTO_INGLES, "quantity": 1, "language_level": "D3"},
            headers=auth,
        )

    assert resp.status_code == 422
    assert not mock_post.called


def test_answer_language_invalido_da_422_sem_chamar_ia(client):
    auth = _autenticar(client, "idioma_invalido@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": _TEXTO_INGLES, "quantity": 1, "language_level": "B1", "answer_language": "fr"},
            headers=auth,
        )

    assert resp.status_code == 422
    assert not mock_post.called


def test_erro_da_ia_retorna_502(client):
    auth = _autenticar(client, "erro_ia@estalo.dev")
    deck = _criar_deck(client, auth)

    resp_erro = Mock()
    resp_erro.status_code = 503
    resp_erro.raise_for_status.side_effect = Exception("indisponível")

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=resp_erro):
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": _TEXTO_INGLES, "quantity": 1, "language_level": "B1"},
            headers=auth,
        )

    assert resp.status_code == 502


def test_deck_de_outro_usuario_da_404_sem_chamar_ia(client):
    dono_auth = _autenticar(client, "dono_leitura@estalo.dev")
    deck = _criar_deck(client, dono_auth)

    intruso_auth = _autenticar(client, "intruso_leitura@estalo.dev")

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": _TEXTO_INGLES, "quantity": 1, "language_level": "B1"},
            headers=intruso_auth,
        )

    assert resp.status_code == 404
    assert not mock_post.called
